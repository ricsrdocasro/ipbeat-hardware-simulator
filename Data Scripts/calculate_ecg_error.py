import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import re

# =============================================================================
# 1. LOAD FLUTTER DATA (CSV)
# =============================================================================
csv_file = 'IPBeat_Raw_Bluetooth_405_Batch.csv'
df_csv = pd.read_csv(csv_file)

# Extract the CSV columns (already in microvolts)
flutter_I   = df_csv['Lead I (uV)'].values
flutter_II  = df_csv['Lead II (uV)'].values
flutter_III = df_csv['Lead III (uV)'].values
flutter_aVR = df_csv['aVR (uV)'].values
flutter_aVL = df_csv['aVL (uV)'].values
flutter_aVF = df_csv['aVF (uV)'].values
flutter_V1  = df_csv['V1 (uV)'].values
flutter_V2  = df_csv['V2 (uV)'].values
flutter_V3  = df_csv['V3 (uV)'].values
flutter_V4  = df_csv['V4 (uV)'].values
flutter_V5  = df_csv['V5 (uV)'].values
flutter_V6  = df_csv['V6 (uV)'].values

# =============================================================================
# 2. LOAD ESP32 DATA (.h) AND EXTRACT ARRAYS
# =============================================================================
h_file = 'ecg_data.h'
with open(h_file, 'r') as f:
    h_content = f.read()

def extrair_array(nome_lead):
    # Searches the .h file for the specific array (e.g., ecg_lead_i)
    padrao = rf'const int16_t PROGMEM ecg_lead_{nome_lead}\[\] = {{([^}}]+)}};'
    match = re.search(padrao, h_content)
    if match:
        str_array = match.group(1).split(',')
        return np.array([int(val.strip()) for val in str_array if val.strip()], dtype=np.float64)
    return None

# Get the 8 physical channels actually transmitted by the ESP32
c_I  = extrair_array('i')
c_II = extrair_array('ii')
c_V1 = extrair_array('v1')
c_V2 = extrair_array('v2')
c_V3 = extrair_array('v3')
c_V4 = extrair_array('v4')
c_V5 = extrair_array('v5')
c_V6 = extrair_array('v6')

# =============================================================================
# 3. THE KEY INSIGHT: VIRTUAL MATH RECREATION
# =============================================================================
# Instead of taking Lead III from PhysioNet, we calculate the "Expected" Lead III
# using the exact same integer math logic applied in the Flutter frontend
c_III = c_II - c_I
c_aVR = -np.floor((c_I + c_II) / 2)
c_aVL = c_I - np.floor(c_II / 2)
c_aVF = c_II - np.floor(c_I / 2)

# =============================================================================
# 4. TIME ALIGNMENT (Cross-Correlation on Lead II)
# =============================================================================
N = min(len(flutter_II), len(c_II))

# Finds the exact time delay from the moment the REC button was pressed
correlation = np.correlate(flutter_II[:N] - np.mean(flutter_II[:N]), 
                           c_II[:N] - np.mean(c_II[:N]), mode='full')
lag = correlation.argmax() - (len(c_II[:N]) - 1)

def alinhar(sinal_flutter, sinal_c):
    if lag > 0:
        f_align = sinal_flutter[lag:]
        c_align = sinal_c[:-lag]
    elif lag < 0:
        f_align = sinal_flutter[:lag]
        c_align = sinal_c[-lag:]
    else:
        f_align = sinal_flutter
        c_align = sinal_c
        
    min_len = min(len(f_align), len(c_align))
    return f_align[:min_len], c_align[:min_len]

# Align all leads
f_I, c_I     = alinhar(flutter_I, c_I)
f_II, c_II   = alinhar(flutter_II, c_II)
f_III, c_III = alinhar(flutter_III, c_III)
f_aVR, c_aVR = alinhar(flutter_aVR, c_aVR)
f_aVL, c_aVL = alinhar(flutter_aVL, c_aVL)
f_aVF, c_aVF = alinhar(flutter_aVF, c_aVF)
f_V1, c_V1   = alinhar(flutter_V1, c_V1)
f_V2, c_V2 = alinhar(flutter_V2, c_V2)
f_V3, c_V3 = alinhar(flutter_V3, c_V3)
f_V4, c_V4 = alinhar(flutter_V4, c_V4)
f_V5, c_V5 = alinhar(flutter_V5, c_V5)
f_V6, c_V6 = alinhar(flutter_V6, c_V6)

# =============================================================================
# 5. ERROR CALCULATION (RMSE)
# =============================================================================
def calc_rmse(f_data, c_data):
    return np.sqrt(np.mean((f_data - c_data)**2))

# Complete Validation Report
print(f"--- IPBEAT VALIDATION REPORT (12 LEADS) ---")
print(f"Synchronization delay: {lag} samples")
print(f"\n--- PHYSICAL CHANNELS (Direct Transmission) ---")
print(f"RMSE Lead I:  {calc_rmse(f_I, c_I):.4f} µV")
print(f"RMSE Lead II: {calc_rmse(f_II, c_II):.4f} µV")
print(f"RMSE V1:      {calc_rmse(f_V1, c_V1):.4f} µV")
print(f"RMSE V2:      {calc_rmse(f_V2, c_V2):.4f} µV")
print(f"RMSE V3:      {calc_rmse(f_V3, c_V3):.4f} µV")
print(f"RMSE V4:      {calc_rmse(f_V4, c_V4):.4f} µV")
print(f"RMSE V5:      {calc_rmse(f_V5, c_V5):.4f} µV")
print(f"RMSE V6:      {calc_rmse(f_V6, c_V6):.4f} µV")

print(f"\n--- VIRTUAL CHANNELS (Flutter Math) ---")
print(f"RMSE Lead III:{calc_rmse(f_III, c_III):.4f} µV")
print(f"RMSE aVR:     {calc_rmse(f_aVR, c_aVR):.4f} µV")
print(f"RMSE aVL:     {calc_rmse(f_aVL, c_aVL):.4f} µV")
print(f"RMSE aVF:     {calc_rmse(f_aVF, c_aVF):.4f} µV")

# =============================================================================
# 6. COMPLETE VALIDATION PLOT (CLINICAL STANDARD 6x2 GRID)
# =============================================================================
# Organizing data in the classic visual order (Left Column vs Right Column)
plot_config = [
    # Column 1 (Limb Leads)      # Column 2 (Precordial Leads)
    ('Lead I', f_I, c_I),        ('V1', f_V1, c_V1),
    ('Lead II', f_II, c_II),     ('V2', f_V2, c_V2),
    ('Lead III', f_III, c_III),  ('V3', f_V3, c_V3),
    ('aVR', f_aVR, c_aVR),       ('V4', f_V4, c_V4),
    ('aVL', f_aVL, c_aVL),       ('V5', f_V5, c_V5),
    ('aVF', f_aVF, c_aVF),       ('V6', f_V6, c_V6)
]

# Creates the figure with a large size (ideal for exporting to the document)
fig, axes = plt.subplots(nrows=6, ncols=2, figsize=(16, 20))
fig.suptitle("IPBeat Transmission Validation: Original Signal vs. Received (Bluetooth)", fontsize=18, fontweight='bold')

# Flattens the 6x2 array of plots for easy looping (indices 0 to 11)
axes = axes.flatten()

for i, (title, f_data, c_data) in enumerate(plot_config):
    ax = axes[i]
    
    # Calculates the specific error to put in the subplot title
    rmse_val = calc_rmse(f_data, c_data)
    
    # Draws the Expected signal (Thick blue) and the Received signal (Thin dashed red)
    ax.plot(c_data, label='Original (C++)', color='#1f77b4', alpha=0.8, linewidth=2.5)
    ax.plot(f_data, label='IPBeat (Flutter)', color='#d62728', linestyle='--', alpha=1.0, linewidth=1.5)
    
    # Subplot formatting
    ax.set_title(f"{title} | RMSE: {rmse_val:.4f} µV", fontsize=12, fontweight='bold', loc='left')
    ax.grid(True, linestyle=':', alpha=0.6)
    
    # Removes X-axis labels on the top plots to avoid visual clutter
    if i < 10:
        ax.set_xticklabels([])
    else:
        ax.set_xlabel('Samples (Time)', fontsize=10)
        
    # Places the legend only on the first plot to save space
    if i == 0:
        ax.legend(loc='upper right', fontsize=10)

# Adjusts spacing to prevent overlap
plt.tight_layout()
fig.subplots_adjust(top=0.95) # Leaves space for the main title

# Saves the image automatically in high resolution!
plt.savefig('Validation_12_Leads_IPBeat.png', dpi=300, bbox_inches='tight')

print("\nPlot generated successfully! The image 'Validation_12_Leads_IPBeat.png' was saved in the folder.")
plt.show()