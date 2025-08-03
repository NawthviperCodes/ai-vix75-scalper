#!/usr/bin/env python3
"""
PROFESSIONAL SUPPLY/DEMAND ZONE BACKTESTER
Enhanced with:
- Zone strength scoring
- Merged zone handling
- Volume-aware detection
- Multi-touch validation
"""

import pandas as pd
import matplotlib.pyplot as plt
from zone_detector import detect_respected_zones
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta

# === CONFIGURATION ===
CONFIG = {
    'data_path': "H1_data.csv",
    'delimiter': '\t',
    'min_zone_strength': 65,       # 0-100 scale (recommended: 65+ for trading)
    'min_touches': 2,              # Minimum zone retests to qualify
    'show_merged_zones': True,     # Visualize combined zones
    'plot_last_n_bars': 500,       # Focus on recent price action
    'zone_opacity': 0.3,           # Visual transparency (0.1-1.0)
    'font_size': 9
}

# === DATA LOADING ===
def load_data():
    """Load and preprocess market data"""
    df = pd.read_csv(
        CONFIG['data_path'], 
        delimiter=CONFIG['delimiter']
    )
    
    # Convert to datetime and rename columns
    df['time'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'])
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close'
    })[['time', 'open', 'high', 'low', 'close']]
    
    # Add dummy volume if missing
    if 'volume' not in df.columns:
        df['volume'] = 1
        
    return df.sort_values('time').reset_index(drop=True)

# === ZONE DETECTION ===
def detect_zones_with_strength(df):
    """Run professional-grade zone detection"""
    demand_zones = [
        z for z in detect_respected_zones(
            df, 
            zone_type='demand',
            min_touches=CONFIG['min_touches']
        ) if z['strength'] >= CONFIG['min_zone_strength']
    ]
    
    supply_zones = [
        z for z in detect_respected_zones(
            df,
            zone_type='supply',
            min_touches=CONFIG['min_touches']
        ) if z['strength'] >= CONFIG['min_zone_strength']
    ]
    
    return demand_zones, supply_zones

# === VISUALIZATION ===
def plot_zones(df, demand_zones, supply_zones):
    """Professional trading chart with zones"""
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(20, 10))
    
    # Trim data to last N bars
    plot_df = df.iloc[-CONFIG['plot_last_n_bars']:]
    
    # Plot price
    ax.plot(
        plot_df['time'], 
        plot_df['close'], 
        label='Price', 
        color='#2c3e50',
        linewidth=1.5,
        alpha=0.9
    )
    
    # Custom grid
    ax.grid(which="major", linestyle=':', linewidth=0.5, color='gray', alpha=0.7)
    
    # Plot Demand Zones
    for zone in demand_zones:
        if zone['timestamp'] < plot_df['time'].iloc[0]:
            continue
            
        color = '#27ae60' if not zone.get('merged') else '#16a085'
        alpha = CONFIG['zone_opacity'] * (zone['strength'] / 100)
        
        rect = Rectangle(
            (zone['timestamp'], zone['zone_low']),
            width=timedelta(hours=12),
            height=zone['zone_high'] - zone['zone_low'],
            facecolor=color,
            alpha=alpha,
            edgecolor=color,
            linestyle='--' if zone.get('merged') else '-',
            linewidth=1
        )
        ax.add_patch(rect)
        
        # Zone label
        label_text = f"D {zone['strength']:.0f}{'*' if zone.get('merged') else ''}"
        ax.text(
            zone['timestamp'], 
            zone['zone_high'],
            label_text,
            color='white',
            backgroundcolor=color,
            fontsize=CONFIG['font_size'],
            bbox=dict(facecolor=color, alpha=0.7, pad=1, edgecolor='none')
        )
    
    # Plot Supply Zones
    for zone in supply_zones:
        if zone['timestamp'] < plot_df['time'].iloc[0]:
            continue
            
        color = '#e74c3c' if not zone.get('merged') else '#c0392b'
        alpha = CONFIG['zone_opacity'] * (zone['strength'] / 100)
        
        rect = Rectangle(
            (zone['timestamp'], zone['zone_low']),
            width=timedelta(hours=12),
            height=zone['zone_high'] - zone['zone_low'],
            facecolor=color,
            alpha=alpha,
            edgecolor=color,
            linestyle='--' if zone.get('merged') else '-',
            linewidth=1
        )
        ax.add_patch(rect)
        
        # Zone label
        label_text = f"S {zone['strength']:.0f}{'*' if zone.get('merged') else ''}"
        ax.text(
            zone['timestamp'], 
            zone['zone_low'],
            label_text,
            color='white',
            backgroundcolor=color,
            fontsize=CONFIG['font_size'],
            bbox=dict(facecolor=color, alpha=0.7, pad=1, edgecolor='none')
        )
    
    # Chart cosmetics
    ax.set_title(
        f"Professional Supply/Demand Zones | Strength ≥ {CONFIG['min_zone_strength']} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        pad=20,
        fontsize=14,
        fontweight='bold'
    )
    ax.set_xlabel("Time", labelpad=10)
    ax.set_ylabel("Price", labelpad=10)
    ax.legend(loc='upper left')
    
    plt.tight_layout()
    return fig

# === MAIN EXECUTION ===
if __name__ == "__main__":
    print("\n⚡ Running Professional Zone Backtest...")
    
    # Load and prepare data
    df = load_data()
    print(f"✅ Loaded {len(df)} bars from {df['time'].iloc[0].date()} to {df['time'].iloc[-1].date()}")
    
    # Detect zones
    demand_zones, supply_zones = detect_zones_with_strength(df)
    print(f"\n🔍 Zone Detection Results:")
    print(f"🟢 Strong Demand Zones: {len([z for z in demand_zones if not z.get('merged')])}")
    print(f"🔴 Strong Supply Zones: {len([z for z in supply_zones if not z.get('merged')])}")
    print(f"🟦 Merged Demand Zones: {len([z for z in demand_zones if z.get('merged')])}")
    print(f"🟥 Merged Supply Zones: {len([z for z in supply_zones if z.get('merged')])}")
    
    # Generate visual report
    fig = plot_zones(df, demand_zones, supply_zones)
    
    # Save and show
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fig.savefig(f"zone_report_{timestamp}.png", dpi=300, bbox_inches='tight')
    print(f"\n💾 Saved visualization to zone_report_{timestamp}.png")
    plt.show()