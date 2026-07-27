import wfdb
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
import sys

# --- CONFIGURATIONS ---
RECORD_NAME = 's0015lre'       # File name (without extension)
SECONDS_TO_VIEW = 4.0          # Seconds to load on screen
CUTOFF_FREQ_HPF = 0.5          # High-pass filter cutoff frequency in Hz (0.5 is standard for ECG)

# --- FILTERING FUNCTION ---
def apply_high_pass_filter(data, fs, cutoff):
    """
    Applies a Butterworth High-Pass filter (order 4) to remove 
    baseline wander.
    """
    nyquist = 0.5 * fs
    normal_cutoff = cutoff / nyquist
    # The 'highpass' filter removes VERY low frequencies (respiration)
    b, a = butter(4, normal_cutoff, btype='high', analog=False)
    
    # Applies the filter to all channels (filtfilt prevents phase delay/QRS distortion)
    filtered_data = np.zeros_like(data)
    for i in range(data.shape[1]):
        filtered_data[:, i] = filtfilt(b, a, data[:, i])
    
    return filtered_data

# ==============================================================================

print(f"Reading the first {SECONDS_TO_VIEW} seconds of {RECORD_NAME}...")

# 1. READ THE DATA
record = wfdb.rdrecord(RECORD_NAME, sampto=int(1000 * SECONDS_TO_VIEW))
fs = record.fs
lead_names = record.sig_name

# 2. APPLY HIGH-PASS FILTER
print(f"Applying High-Pass Filter ({CUTOFF_FREQ_HPF} Hz) to flatten the baseline...")
sinal_filtrado = apply_high_pass_filter(record.p_signal, fs, CUTOFF_FREQ_HPF)

print(sinal_filtrado.shape)

# 3. PREPARE THE SCREEN
print(lead_names)
plot_lead_idx = lead_names[0]  # Forcing the use of Lead I!

time_vector = np.arange(sinal_filtrado.shape[0]) / fs

# --- INTERACTIVE SCREEN ---
fig, ax = plt.subplots(figsize=(14, 6))

# Plotting FILTERED Lead I
ax.plot(time_vector, sinal_filtrado[:, 1], color='#FF1744', linewidth=1.5)

ax.set_title(f"Lead I (Filtered)\n1st Click: START of P Wave | 2nd Click: END of T Wave", 
             fontsize=14, fontweight='bold')
ax.set_xlabel("Time (seconds)")
ax.set_ylabel("Amplitude (mV)")
ax.grid(True, linestyle='--', alpha=0.6)

# Zero line (to verify the baseline is perfect)
ax.axhline(0, color='black', linewidth=0.8, linestyle='-')

print("\n>>> WINDOW OPEN! Double click the plot to crop the signal. <<<")
plt.tight_layout()

# Pauses and waits for 2 clicks
pontos = plt.ginput(2, timeout=0) 
plt.close() 

if len(pontos) < 2:
    print("Selection canceled or incomplete. Exiting...")
    sys.exit()

# 4. PROCESS THE CROP
t_start = pontos[0][0]
t_end = pontos[1][0]

if t_start > t_end:
    t_start, t_end = t_end, t_start

idx_start = int(t_start * fs)
idx_end = int(t_end * fs)

print(f"\nSelected crop: from {t_start:.3f}s to {t_end:.3f}s")

# ATTENTION: We crop the ALREADY FILTERED data to avoid jumps
ecg_chunk = sinal_filtrado[idx_start:idx_end, :]
num_samples = ecg_chunk.shape[0]

# Scale to integers (x1000)
ecg_scaled = np.round(ecg_chunk * 1000).astype(np.int16)

# 5. EXPORT TO C++ (PROGMEM)
output_filename = "ecg_data.h"
print(f"Generating {output_filename} with {num_samples} samples ({(num_samples/fs):.3f}s loop)...")

with open(output_filename, 'w') as f:
    f.write("// File generated via interactive cropping (Filtered Signal)\n")
    f.write("#include <pgmspace.h>\n\n")
    f.write(f"const int NUM_SAMPLES = {num_samples};\n")
    f.write(f"const int SAMPLE_RATE_HZ = {int(fs)};\n\n")

    for channel_idx, lead in enumerate(lead_names):
        safe_lead_name = lead.replace(" ", "_").replace("-", "_")
        
        f.write(f"// Lead: {safe_lead_name}\n")
        f.write(f"const int16_t PROGMEM ecg_lead_{safe_lead_name}[] = {{\n    ")
        
        channel_data = ecg_scaled[:, channel_idx]
        
        for i, val in enumerate(channel_data):
            f.write(f"{val}, ")
            if (i + 1) % 15 == 0:
                f.write("\n    ")
        
        f.write("\n};\n\n")

print("\nSuccess! ecg_data.h file ready for use.")