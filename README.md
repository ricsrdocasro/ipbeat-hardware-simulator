## Wireless 12-Lead ECG Acquisition via a Hardware Simulator

This repository contains the firmware, analysis scripts, and raw data supporting the evaluation of a wireless 12-lead ECG telemonitoring architecture. The project utilizes a dual-core Real-Time Operating System (RTOS) on an ESP32-S3 microcontroller to simulate the clinical-grade ADS1298 analog front-end. To mitigate Operating System-level Bluetooth Low Energy (BLE) bottlenecks, the firmware employs a batching protocol that groups 15 samples into 405-byte payloads transmitted at 15 ms intervals.

# Repository Contents: 
Firmware: This folder contains only the src directory with the C++ source code and the platformio.ini configuration file for the ESP32-S3 hardware simulator. The project is specifically designed for a CYD (Cheap Yellow Display) ESP32 board, and the firmware manages the 1000 Hz acquisition loop and the optimized BLE transmission stack.

Raw Data: Captured CSV logs of continuous streaming trials. Note: These logs were captured using a custom cross-platform frontend interface that is not included in this repository.

Data Scripts: Python scripts utilized to calculate network metrics (packet loss, jitter) and mathematically evaluate signal fidelity (cross-correlation and Root Mean Square Error) between the original digital source and the transmitted BLE payloads. 

# Steps to Reproduce:

# Part 1: Hardware Setup & Transmission
Open the Firmware directory using an IDE equipped with the PlatformIO extension (such as VS Code).

Do not modify the build environment; the included platformio.ini file already contains all specific board configurations, library dependencies, and build flags required for the CYD ESP32-S3 board used in this architecture.

Build and flash the RTOS firmware onto the CYD ESP32 microcontroller.

Once running, the hardware simulator will automatically begin looping pre-recorded synthetic ECG signals (based on the PhysioNet dataset).

To capture live data, connect to the ESP32-S3 via a BLE-compatible receiver script or application capable of handling the 15 ms polling interval and 512-byte MTU limits.

# Part 2: Data Analysis & Fidelity Verification
Navigate to the Raw Data folder to access the pre-captured baseline (USB) and experimental (BLE) transmission logs.

Run the provided Python scripts in the Data Scripts folder against these raw logs.

The scripts will perform temporal alignment via mathematical cross-correlation and output the Root Mean Square Error (RMSE) for both physical and virtual leads, replicating the results (RMSE < 3 µV) presented in the associated manuscript.
