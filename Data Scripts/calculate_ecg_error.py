import numpy as np
import pandas as pd
import re

# =============================================================================
# 1. LOAD FLUTTER DATA (CSV)
# =============================================================================
# Trim the first 500 samples to skip the initial partial QRS complex (ONLY FOR USB)
trim_start_usb = 500 

csv_usb = 'IPBeat_Raw_USB_405_Batch.csv'
csv_ble = 'IPBeat_Raw_Bluetooth_405_Batch.csv'

df_usb = pd.read_csv(csv_usb)
df_ble = pd.read_csv(csv_ble)

# =============================================================================
# 2. LOAD ESP32 DATA (.h) AND EXTRACT ARRAYS
# =============================================================================
h_file = 'ecg_data.h'
with open(h_file, 'r') as f:
    h_content = f.read()

def extrair_array(nome_lead):
    padrao = rf'const int16_t PROGMEM ecg_lead_{nome_lead}\[\] = {{([^}}]+)}};'
    match = re.search(padrao, h_content)
    if match:
        str_array = match.group(1).split(',')
        return np.array([int(val.strip()) for val in str_array if val.strip()], dtype=np.float64)
    return None

c_I  = extrair_array('i')
c_II = extrair_array('ii')
c_V1 = extrair_array('v1')
c_V2 = extrair_array('v2')
c_V3 = extrair_array('v3')
c_V4 = extrair_array('v4')
c_V5 = extrair_array('v5')
c_V6 = extrair_array('v6')

# =============================================================================
# 3. RECREATE VIRTUAL MATHEMATICS
# =============================================================================
c_III = c_II - c_I
c_aVR = -np.floor((c_I + c_II) / 2)
c_aVL = c_I - np.floor(c_II / 2)
c_aVF = c_II - np.floor(c_I / 2)

# =============================================================================
# 4. TIME ALIGNMENT (Calculate Lag via Lead II)
# =============================================================================
# Trim USB Lead II, but leave BLE Lead II intact
usb_II = df_usb['Lead II (uV)'].values[trim_start_usb:]
ble_II = df_ble['Lead II (uV)'].values

def find_lag(f_data, c_data):
    N = min(len(f_data), len(c_data))
    correlation = np.correlate(f_data[:N] - np.mean(f_data[:N]), 
                               c_data[:N] - np.mean(c_data[:N]), mode='full')
    return correlation.argmax() - (len(c_data[:N]) - 1)

lag_usb = find_lag(usb_II, c_II)
lag_ble = find_lag(ble_II, c_II)

def apply_lag(f_data, c_data, lag):
    if lag > 0:
        f_align = f_data[lag:]
        c_align = c_data[:-lag]
    elif lag < 0:
        f_align = f_data[:lag]
        c_align = c_data[-lag:]
    else:
        f_align = f_data
        c_align = c_data
    min_len = min(len(f_align), len(c_align))
    return f_align[:min_len], c_align[:min_len]

# =============================================================================
# 5. METRICS CALCULATION
# =============================================================================
def calc_metrics(f_data, c_data):
    rmse = np.sqrt(np.mean((f_data - c_data)**2))
    
    mean_c = np.mean(c_data)
    cvrmse = (rmse / np.abs(mean_c)) * 100 if mean_c != 0 else float('inf')
    
    range_c = np.max(c_data) - np.min(c_data)
    nrmse = (rmse / range_c) * 100 if range_c != 0 else float('inf')
    
    return rmse, cvrmse, nrmse

# =============================================================================
# 6. PROCESS LEADS AND GENERATE COMPACT TABLE FOR WORD
# =============================================================================
leads_config = [
    ('DI', 'Lead I (uV)', c_I, 'Physical'),
    ('DII', 'Lead II (uV)', c_II, 'Physical'),
    ('DIII', 'Lead III (uV)', c_III, 'Virtual'),
    ('aVR', 'aVR (uV)', c_aVR, 'Virtual'),
    ('aVL', 'aVL (uV)', c_aVL, 'Virtual'),
    ('aVF', 'aVF (uV)', c_aVF, 'Virtual'),
    ('V1', 'V1 (uV)', c_V1, 'Physical'),
    ('V2', 'V2 (uV)', c_V2, 'Physical'),
    ('V3', 'V3 (uV)', c_V3, 'Physical'),
    ('V4', 'V4 (uV)', c_V4, 'Physical'),
    ('V5', 'V5 (uV)', c_V5, 'Physical'),
    ('V6', 'V6 (uV)', c_V6, 'Physical')
]

table_data = []

for lead_name, col_name, c_data, lead_type in leads_config:
    # Process USB (Trimmed)
    f_usb_raw = df_usb[col_name].values[trim_start_usb:]
    f_usb, c_usb_align = apply_lag(f_usb_raw, c_data, lag_usb)
    rmse_u, cvrmse_u, nrmse_u = calc_metrics(f_usb, c_usb_align)
    
    # Process BLE (Untrimmed)
    f_ble_raw = df_ble[col_name].values
    f_ble, c_ble_align = apply_lag(f_ble_raw, c_data, lag_ble)
    rmse_b, cvrmse_b, nrmse_b = calc_metrics(f_ble, c_ble_align)
    
    # Append Compact Row (All metrics on one line)
    table_data.append({
        "Lead": lead_name,
        "Type": lead_type,
        "RMSE USB (µV)": f"{rmse_u:.4f}",
        "CVRMSE / NRMSE USB (%)": f"{cvrmse_u:.2f} / {nrmse_u:.2f}",
        "RMSE BLE (µV)": f"{rmse_b:.4f}",
        "CVRMSE / NRMSE BLE (%)": f"{cvrmse_b:.2f} / {nrmse_b:.2f}"
    })

# Convert to a Pandas DataFrame
df_results = pd.DataFrame(table_data)

print("--- TAB-SEPARATED TABLE (COPY THE TEXT BELOW) ---\n")
print(df_results.to_csv(sep='\t', index=False))

print("\n--- SYNCHRONIZATION INFO ---")
print(f"USB Lag Applied: {lag_usb} samples (after {trim_start_usb} sample trim)")
print(f"BLE Lag Applied: {lag_ble} samples (no initial trim)")

# MAGIC TRICK: Attempt to copy directly to your computer's clipboard!
try:
    df_results.to_clipboard(index=False)
    print("\n[SUCCESS] Table automatically copied to your clipboard! Try pressing Ctrl+V in Word right now.")
except Exception as e:
    pass