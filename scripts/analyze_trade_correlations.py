#!/usr/bin/env python3
"""
Trade Correlation Analysis Script
Analyzes PRT trade data to find correlations with profitable/losing trades.
Focuses on prob_up, p10, p90 and their relationship to profit/loss.
"""

import sys
import os

try:
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns
    from scipy import stats
    from scipy.stats import pearsonr, spearmanr
    import warnings
    warnings.filterwarnings('ignore')
except ImportError as e:
    print("ERROR: Missing required dependencies.")
    print("Please install: pip install pandas numpy matplotlib seaborn scipy")
    print(f"Missing module: {e.name}")
    sys.exit(1)

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)

def load_data(filepath):
    """Load and preprocess trade data."""
    print("Loading trade data...")
    df = pd.read_csv(filepath)
    
    # Filter only closed trades
    df = df[df['closed'] == True].copy()
    
    # Convert boolean columns
    bool_cols = ['is_winner', 'is_loser', 'is_breakeven', 'closed']
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].astype(bool)
    
    # Convert numeric columns
    numeric_cols = ['profit_loss', 'profit_loss_percent', 'prob_up', 'p10', 'p90', 
                   'mean', 'edge', 'dist1', 'n', 'hold_time_minutes']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    print(f"✓ Loaded {len(df)} closed trades")
    return df

def basic_statistics(df):
    """Print basic statistics about the trades."""
    print("\n" + "="*80)
    print("BASIC STATISTICS")
    print("="*80)
    
    winners = df[df['is_winner'] == True]
    losers = df[df['is_loser'] == True]
    breakeven = df[df['is_breakeven'] == True]
    
    print(f"\nTotal closed trades: {len(df)}")
    print(f"  Winners: {len(winners)} ({len(winners)/len(df)*100:.1f}%)")
    print(f"  Losers: {len(losers)} ({len(losers)/len(df)*100:.1f}%)")
    print(f"  Breakeven: {len(breakeven)} ({len(breakeven)/len(df)*100:.1f}%)")
    
    print(f"\nTotal P&L: ${df['profit_loss'].sum():.2f}")
    print(f"Average P&L per trade: ${df['profit_loss'].mean():.2f}")
    print(f"Average P&L % per trade: {df['profit_loss_percent'].mean():.4f}%")
    
    print(f"\nWinners - Avg P&L: ${winners['profit_loss'].mean():.2f}, Avg %: {winners['profit_loss_percent'].mean():.4f}%")
    print(f"Losers - Avg P&L: ${losers['profit_loss'].mean():.2f}, Avg %: {losers['profit_loss_percent'].mean():.4f}%")

def analyze_correlations(df):
    """Analyze correlations between variables and profit/loss."""
    print("\n" + "="*80)
    print("CORRELATION ANALYSIS")
    print("="*80)
    
    # Variables of interest
    variables = ['prob_up', 'p10', 'p90', 'mean', 'edge', 'dist1', 'n']
    
    # Filter out NaN values for correlation
    df_clean = df[['profit_loss', 'profit_loss_percent'] + variables].dropna()
    
    print("\nCorrelation with Profit/Loss ($):")
    print("-" * 80)
    correlations_pl = {}
    for var in variables:
        if var in df_clean.columns:
            pearson_corr, pearson_p = pearsonr(df_clean[var], df_clean['profit_loss'])
            spearman_corr, spearman_p = spearmanr(df_clean[var], df_clean['profit_loss'])
            correlations_pl[var] = {
                'pearson': pearson_corr,
                'pearson_p': pearson_p,
                'spearman': spearman_corr,
                'spearman_p': spearman_p
            }
            sig_pearson = "***" if pearson_p < 0.001 else "**" if pearson_p < 0.01 else "*" if pearson_p < 0.05 else ""
            sig_spearman = "***" if spearman_p < 0.001 else "**" if spearman_p < 0.01 else "*" if spearman_p < 0.05 else ""
            print(f"{var:12s} | Pearson: {pearson_corr:7.4f} {sig_pearson:3s} (p={pearson_p:.4f}) | "
                  f"Spearman: {spearman_corr:7.4f} {sig_spearman:3s} (p={spearman_p:.4f})")
    
    print("\nCorrelation with Profit/Loss (%):")
    print("-" * 80)
    correlations_pct = {}
    for var in variables:
        if var in df_clean.columns:
            pearson_corr, pearson_p = pearsonr(df_clean[var], df_clean['profit_loss_percent'])
            spearman_corr, spearman_p = spearmanr(df_clean[var], df_clean['profit_loss_percent'])
            correlations_pct[var] = {
                'pearson': pearson_corr,
                'pearson_p': pearson_p,
                'spearman': spearman_corr,
                'spearman_p': spearman_p
            }
            sig_pearson = "***" if pearson_p < 0.001 else "**" if pearson_p < 0.01 else "*" if pearson_p < 0.05 else ""
            sig_spearman = "***" if spearman_p < 0.001 else "**" if spearman_p < 0.01 else "*" if spearman_p < 0.05 else ""
            print(f"{var:12s} | Pearson: {pearson_corr:7.4f} {sig_pearson:3s} (p={pearson_p:.4f}) | "
                  f"Spearman: {spearman_corr:7.4f} {sig_spearman:3s} (p={spearman_p:.4f})")
    
    return correlations_pl, correlations_pct

def compare_winners_losers(df):
    """Compare key variables between winners and losers."""
    print("\n" + "="*80)
    print("WINNERS vs LOSERS COMPARISON")
    print("="*80)
    
    winners = df[df['is_winner'] == True]
    losers = df[df['is_loser'] == True]
    
    variables = ['prob_up', 'p10', 'p90', 'mean', 'edge', 'dist1', 'n']
    
    print(f"\n{'Variable':<12} {'Winners Mean':<15} {'Losers Mean':<15} {'Difference':<15} {'p-value':<10} {'Significant':<10}")
    print("-" * 80)
    
    results = {}
    for var in variables:
        if var in df.columns:
            winner_vals = winners[var].dropna()
            loser_vals = losers[var].dropna()
            
            if len(winner_vals) > 0 and len(loser_vals) > 0:
                winner_mean = winner_vals.mean()
                loser_mean = loser_vals.mean()
                diff = winner_mean - loser_mean
                
                # T-test
                t_stat, p_value = stats.ttest_ind(winner_vals, loser_vals)
                significant = "Yes" if p_value < 0.05 else "No"
                
                results[var] = {
                    'winner_mean': winner_mean,
                    'loser_mean': loser_mean,
                    'difference': diff,
                    'p_value': p_value,
                    'significant': p_value < 0.05
                }
                
                print(f"{var:<12} {winner_mean:>14.6f} {loser_mean:>14.6f} {diff:>14.6f} {p_value:>9.4f} {significant:>10}")
    
    return results

def analyze_prob_up_buckets(df):
    """Analyze performance by prob_up buckets."""
    print("\n" + "="*80)
    print("PERFORMANCE BY prob_up BUCKETS")
    print("="*80)
    
    # Create buckets
    df['prob_up_bucket'] = pd.cut(df['prob_up'], bins=[0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0], 
                                  labels=['0-0.3', '0.3-0.4', '0.4-0.5', '0.5-0.6', '0.6-0.7', '0.7+'])
    
    print("\nBucket Analysis:")
    print("-" * 80)
    print(f"{'Bucket':<12} {'Count':<8} {'Win Rate':<10} {'Avg P&L $':<12} {'Avg P&L %':<12}")
    print("-" * 80)
    
    for bucket in df['prob_up_bucket'].cat.categories:
        bucket_data = df[df['prob_up_bucket'] == bucket]
        if len(bucket_data) > 0:
            win_rate = bucket_data['is_winner'].sum() / len(bucket_data) * 100
            avg_pl = bucket_data['profit_loss'].mean()
            avg_pl_pct = bucket_data['profit_loss_percent'].mean()
            print(f"{bucket:<12} {len(bucket_data):<8} {win_rate:>9.1f}% {avg_pl:>11.2f} {avg_pl_pct:>11.4f}%")

def analyze_p10_p90(df):
    """Analyze p10 and p90 relationships."""
    print("\n" + "="*80)
    print("p10 and p90 ANALYSIS")
    print("="*80)
    
    # Calculate spread (p90 - p10) as a measure of uncertainty
    df['p_spread'] = df['p90'] - df['p10']
    
    winners = df[df['is_winner'] == True]
    losers = df[df['is_loser'] == True]
    
    print("\nWinners vs Losers:")
    print("-" * 80)
    print(f"{'Metric':<15} {'Winners':<15} {'Losers':<15} {'Difference':<15}")
    print("-" * 80)
    
    for metric in ['p10', 'p90', 'p_spread']:
        if metric in df.columns:
            w_mean = winners[metric].mean()
            l_mean = losers[metric].mean()
            diff = w_mean - l_mean
            print(f"{metric:<15} {w_mean:>14.6f} {l_mean:>14.6f} {diff:>14.6f}")
    
    # Correlation with profit
    print("\nCorrelation with Profit/Loss:")
    print("-" * 80)
    df_clean = df[['profit_loss', 'p10', 'p90', 'p_spread']].dropna()
    for metric in ['p10', 'p90', 'p_spread']:
        if metric in df_clean.columns:
            corr, p_val = pearsonr(df_clean[metric], df_clean['profit_loss'])
            sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
            print(f"{metric:<15} Correlation: {corr:7.4f} {sig:3s} (p={p_val:.4f})")

def create_visualizations(df):
    """Create visualization plots."""
    print("\n" + "="*80)
    print("GENERATING VISUALIZATIONS")
    print("="*80)
    
    # Create figure with subplots
    fig = plt.figure(figsize=(16, 12))
    
    # 1. prob_up vs profit_loss scatter
    ax1 = plt.subplot(3, 3, 1)
    winners = df[df['is_winner'] == True]
    losers = df[df['is_loser'] == True]
    ax1.scatter(winners['prob_up'], winners['profit_loss'], alpha=0.5, label='Winners', color='green', s=20)
    ax1.scatter(losers['prob_up'], losers['profit_loss'], alpha=0.5, label='Losers', color='red', s=20)
    ax1.set_xlabel('prob_up')
    ax1.set_ylabel('Profit/Loss ($)')
    ax1.set_title('prob_up vs Profit/Loss')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. p10 vs profit_loss scatter
    ax2 = plt.subplot(3, 3, 2)
    ax2.scatter(winners['p10'], winners['profit_loss'], alpha=0.5, label='Winners', color='green', s=20)
    ax2.scatter(losers['p10'], losers['profit_loss'], alpha=0.5, label='Losers', color='red', s=20)
    ax2.set_xlabel('p10')
    ax2.set_ylabel('Profit/Loss ($)')
    ax2.set_title('p10 vs Profit/Loss')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. p90 vs profit_loss scatter
    ax3 = plt.subplot(3, 3, 3)
    ax3.scatter(winners['p90'], winners['profit_loss'], alpha=0.5, label='Winners', color='green', s=20)
    ax3.scatter(losers['p90'], losers['profit_loss'], alpha=0.5, label='Losers', color='red', s=20)
    ax3.set_xlabel('p90')
    ax3.set_ylabel('Profit/Loss ($)')
    ax3.set_title('p90 vs Profit/Loss')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # 4. prob_up distribution by outcome
    ax4 = plt.subplot(3, 3, 4)
    df['outcome'] = df.apply(lambda x: 'Winner' if x['is_winner'] else 'Loser' if x['is_loser'] else 'Breakeven', axis=1)
    for outcome in ['Winner', 'Loser', 'Breakeven']:
        data = df[df['outcome'] == outcome]['prob_up'].dropna()
        if len(data) > 0:
            ax4.hist(data, alpha=0.5, label=outcome, bins=20)
    ax4.set_xlabel('prob_up')
    ax4.set_ylabel('Frequency')
    ax4.set_title('prob_up Distribution by Outcome')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    # 5. p10 distribution by outcome
    ax5 = plt.subplot(3, 3, 5)
    for outcome in ['Winner', 'Loser', 'Breakeven']:
        data = df[df['outcome'] == outcome]['p10'].dropna()
        if len(data) > 0:
            ax5.hist(data, alpha=0.5, label=outcome, bins=20)
    ax5.set_xlabel('p10')
    ax5.set_ylabel('Frequency')
    ax5.set_title('p10 Distribution by Outcome')
    ax5.legend()
    ax5.grid(True, alpha=0.3)
    
    # 6. p90 distribution by outcome
    ax6 = plt.subplot(3, 3, 6)
    for outcome in ['Winner', 'Loser', 'Breakeven']:
        data = df[df['outcome'] == outcome]['p90'].dropna()
        if len(data) > 0:
            ax6.hist(data, alpha=0.5, label=outcome, bins=20)
    ax6.set_xlabel('p90')
    ax6.set_ylabel('Frequency')
    ax6.set_title('p90 Distribution by Outcome')
    ax6.legend()
    ax6.grid(True, alpha=0.3)
    
    # 7. Correlation heatmap
    ax7 = plt.subplot(3, 3, 7)
    corr_vars = ['profit_loss', 'profit_loss_percent', 'prob_up', 'p10', 'p90', 'mean', 'edge']
    corr_df = df[corr_vars].corr()
    sns.heatmap(corr_df, annot=True, fmt='.3f', cmap='coolwarm', center=0, ax=ax7, square=True)
    ax7.set_title('Correlation Heatmap')
    
    # 8. Box plot: prob_up by outcome
    ax8 = plt.subplot(3, 3, 8)
    df_box = df[df['outcome'].isin(['Winner', 'Loser'])].copy()
    sns.boxplot(data=df_box, x='outcome', y='prob_up', ax=ax8)
    ax8.set_title('prob_up by Outcome')
    ax8.grid(True, alpha=0.3)
    
    # 9. Box plot: p90-p10 spread by outcome
    ax9 = plt.subplot(3, 3, 9)
    df['p_spread'] = df['p90'] - df['p10']
    df_box = df[df['outcome'].isin(['Winner', 'Loser'])].copy()
    sns.boxplot(data=df_box, x='outcome', y='p_spread', ax=ax9)
    ax9.set_title('p90-p10 Spread by Outcome')
    ax9.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_file = 'trade_correlation_analysis.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✓ Saved visualization to {output_file}")
    plt.close()

def main():
    """Main analysis function."""
    print("="*80)
    print("TRADE CORRELATION ANALYSIS")
    print("="*80)
    
    # Load data - try multiple possible paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        os.path.join(script_dir, '../prt_trade_analysis.csv'),
        os.path.join(script_dir, '../../prt_trade_analysis.csv'),
        'prt_trade_analysis.csv',
        '../prt_trade_analysis.csv'
    ]
    
    filepath = None
    for path in possible_paths:
        if os.path.exists(path):
            filepath = path
            break
    
    if filepath is None:
        print("ERROR: Could not find prt_trade_analysis.csv")
        print("Tried paths:")
        for path in possible_paths:
            print(f"  - {path}")
        return
    
    print(f"Using data file: {filepath}")
    df = load_data(filepath)
    
    if len(df) == 0:
        print("ERROR: No closed trades found in data!")
        return
    
    # Run analyses
    basic_statistics(df)
    correlations_pl, correlations_pct = analyze_correlations(df)
    winner_loser_comparison = compare_winners_losers(df)
    analyze_prob_up_buckets(df)
    analyze_p10_p90(df)
    create_visualizations(df)
    
    # Summary
    print("\n" + "="*80)
    print("KEY FINDINGS SUMMARY")
    print("="*80)
    
    print("\nTop Correlations with Profit/Loss ($):")
    sorted_corr = sorted(correlations_pl.items(), key=lambda x: abs(x[1]['pearson']), reverse=True)
    for var, corr_data in sorted_corr[:5]:
        print(f"  {var}: {corr_data['pearson']:.4f} (p={corr_data['pearson_p']:.4f})")
    
    print("\nVariables with Significant Differences (Winners vs Losers):")
    for var, result in winner_loser_comparison.items():
        if result['significant']:
            direction = "Higher" if result['difference'] > 0 else "Lower"
            print(f"  {var}: {direction} in winners (diff={result['difference']:.6f}, p={result['p_value']:.4f})")
    
    print("\n" + "="*80)
    print("Analysis complete!")
    print("="*80)

if __name__ == "__main__":
    main()

