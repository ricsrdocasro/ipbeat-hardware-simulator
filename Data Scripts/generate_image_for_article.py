import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import re

# =============================================================================
# 1. LOAD FLUTTER DATA (CSV - USB AND BLUETOOTH)
# =============================================================================
# Load Bluetooth data
df_ble = pd.read_csv('IPBeat_Raw_Bluetooth_405_Batch.csv')
flutter_ble_II = df_ble['Lead II (uV)'].values

# Load USB data
df_usb = pd.read_csv('IPBeat_Raw_USB_405_Batch.csv')
flutter_usb_II = df_usb['Lead II (uV)'].values

# =============================================================================
# 2. LOAD ESP32 DATA (.h) AND EXTRACT ORIGINAL LEAD II
# =============================================================================
h_file = 'ecg_data.h'
with open(h_file, 'r') as f:
    h_content = f.read()

def extrair_array(nome_lead):
    # Search for the specific array in the .h file
    padrao = rf'const int16_t PROGMEM ecg_lead_{nome_lead}\[\] = {{([^}}]+)}};'
    match = re.search(padrao, h_content)
    if match:
        str_array = match.group(1).split(',')
        return np.array([int(val.strip()) for val in str_array if val.strip()], dtype=np.float64)
    return None

# Get only the original physical Lead II
c_II = extrair_array('ii')

# =============================================================================
# 3. TIME ALIGNMENT FUNCTION (Cross-Correlation)
# =============================================================================
def alinhar_e_calcular_erro(sinal_flutter, sinal_c):
    # Find the minimum length to avoid out-of-bounds errors
    N = min(len(sinal_flutter), len(sinal_c))
    
    # Cross-correlation to find the time lag
    correlation = np.correlate(sinal_flutter[:N] - np.mean(sinal_flutter[:N]), 
                               sinal_c[:N] - np.mean(sinal_c[:N]), mode='full')
    lag = correlation.argmax() - (len(sinal_c[:N]) - 1)
    
    # Apply the alignment by slicing the arrays
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
    f_final = f_align[:min_len]
    c_final = c_align[:min_len]
    
    # Calculate RMSE
    rmse = np.sqrt(np.mean((f_final - c_final)**2))
    
    return f_final, c_final, lag, rmse

# Process alignment for both USB and BLE
f_usb_align, c_usb_align, lag_usb, rmse_usb = alinhar_e_calcular_erro(flutter_usb_II, c_II)
f_ble_align, c_ble_align, lag_ble, rmse_ble = alinhar_e_calcular_erro(flutter_ble_II, c_II)

print(f"--- LEAD II SYNCHRONIZATION REPORT ---")
print(f"USB: {lag_usb} samples lag | RMSE: {rmse_usb:.4f} µV")
print(f"BLE: {lag_ble} samples lag | RMSE: {rmse_ble:.4f} µV")

# =============================================================================
# 4. PLOT SIDE-BY-SIDE (1 Row, 2 Columns) - HIGH CONTRAST FOR PUBLICATION
# =============================================================================
fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(16, 6))
fig.suptitle("IPBeat Transmission Integrity Comparison: Lead II (USB vs. Bluetooth)", fontsize=16, fontweight='bold')

# High contrast colors for perfect overlap (low RMSE)
color_original = 'black'        # Neutral shadow
color_usb = '#009E73'           # Colorblind-friendly Green (strong)
color_ble = '#D55E00'           # Colorblind-friendly Orange/Red (strong)

# --- GRAPH 1: USB ---
ax1 = axes[0]
# Original signal as a 'shadow' (thick and semi-transparent)
ax1.plot(c_usb_align, label='Original (Flash C++)', color=color_original, alpha=0.25, linewidth=4.5)
# Received signal cutting over (thin, dashed and opaque)
ax1.plot(f_usb_align, label='Received via USB', color=color_usb, linestyle='--', alpha=1.0, linewidth=1.5)

ax1.set_title(f"USB Transmission | RMSE: {rmse_usb:.4f} µV", fontsize=14, fontweight='bold', loc='left')
ax1.grid(True, linestyle=':', alpha=0.6)
ax1.set_xlabel('Samples (Time)', fontsize=12)
ax1.set_ylabel('Amplitude (µV)', fontsize=12)
ax1.legend(loc='upper right', fontsize=11)

# --- GRAPH 2: BLUETOOTH ---
ax2 = axes[1]
# Original signal as a 'shadow' (thick and semi-transparent)
ax2.plot(c_ble_align, label='Original (Flash C++)', color=color_original, alpha=0.25, linewidth=4.5)
# Received signal cutting over (thin, dashed and opaque)
ax2.plot(f_ble_align, label='Received via Bluetooth', color=color_ble, linestyle='--', alpha=1.0, linewidth=1.5)

ax2.set_title(f"Bluetooth Transmission | RMSE: {rmse_ble:.4f} µV", fontsize=14, fontweight='bold', loc='left')
ax2.grid(True, linestyle=':', alpha=0.6)
ax2.set_xlabel('Samples (Time)', fontsize=12)
ax2.legend(loc='upper right', fontsize=11)

# Final adjustments and export
plt.tight_layout()
fig.subplots_adjust(top=0.88) # Space for the global title

# Save the high-resolution image
filename = 'Validation_Lead_II_USB_vs_BLE_HighContrast.png'
plt.savefig(filename, dpi=300, bbox_inches='tight')

print(f"\nPlot generated successfully! The image '{filename}' has been saved for the paper.")
plt.show()