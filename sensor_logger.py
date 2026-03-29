"""
Cooling Rate Logger
- Displays T_plate live while waiting
- Starts 30s test automatically when pump turns on
- Reports cooling rate, total drop, and thermal metrics
- Saves CSV and PNG

Requirements: pip install pyserial matplotlib
"""

import serial
import csv
import matplotlib.pyplot as plt
from datetime import datetime
import time
import sys

# ── CONFIG ─────────────────────────────────────────────
PORT          = "COM3"  # Change to your Arduino's COM port
BAUD          = 9600
FLOW_TRIGGER  = 0.5     # L/min to detect pump on
TEST_DURATION = 120.0    # seconds to log
# ───────────────────────────────────────────────────────

FLUID_SPECIFIC_HEAT = 4186.0
FLUID_DENSITY       = 1.0

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_FILE  = f"coolingrate_{timestamp}.csv"
PNG_FILE  = f"coolingrate_{timestamp}.png"

# ── Connect ────────────────────────────────────────────
try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    print(f"\nConnected to {PORT} at {BAUD} baud.")
    time.sleep(2)
    ser.reset_input_buffer()
except serial.SerialException as e:
    print(f"ERROR: Could not open {PORT}\n{e}")
    import serial.tools.list_ports
    print("\nAvailable ports:")
    for p in serial.tools.list_ports.comports():
        print(f"  {p.device} — {p.description}")
    sys.exit(1)

def read_line():
    while True:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line or line.startswith("time"):
            continue
        parts = line.split(",")
        if len(parts) != 8:
            continue
        try:
            return (float(parts[0]), float(parts[1]), float(parts[2]),
                    float(parts[3]), float(parts[4]), float(parts[5]),
                    float(parts[6]), float(parts[7]))
        except ValueError:
            continue

def calculate_metrics(psi_in, psi_out, temp_in, temp_out, temp_hx, flow_data):
    if len(psi_in) < 5:
        return None
    avg_t_in   = sum(temp_in)   / len(temp_in)
    avg_t_out  = sum(temp_out)  / len(temp_out)
    avg_t_hx   = sum(temp_hx)   / len(temp_hx)
    avg_flow   = sum(flow_data) / len(flow_data)
    avg_dp_psi = sum(p1 - p2 for p1, p2 in zip(psi_in, psi_out)) / len(psi_in)
    avg_dp_pa  = avg_dp_psi * 6894.76

    flow_kg_s  = (avg_flow / 60.0) * FLUID_DENSITY
    Q          = flow_kg_s * FLUID_SPECIFIC_HEAT * (avg_t_out - avg_t_in)
    R_th       = (avg_t_hx - avg_t_in) / Q if Q > 0 else float('inf')
    P_pump     = avg_dp_pa * ((avg_flow / 60.0) / 1000.0)
    efficiency = Q / P_pump if P_pump > 0 else float('inf')

    return {"avg_t_in": avg_t_in, "avg_t_out": avg_t_out, "avg_t_hx": avg_t_hx,
            "avg_flow": avg_flow, "avg_dp_psi": avg_dp_psi, "avg_dp_pa": avg_dp_pa,
            "Q": Q, "R_th": R_th, "P_pump": P_pump, "efficiency": efficiency}

def save_graph(times, psi_in, psi_out, temp_in, temp_out, temp_hx,
               flow_data, initial_t, final_t, cooling_rate, metrics):
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True)
    fig.suptitle(f"Cooling Rate Test — {timestamp}", fontsize=13)

    dp = [p1 - p2 for p1, p2 in zip(psi_in, psi_out)]

    axes[0].plot(times, psi_in,  label="Inlet Pressure",  color="steelblue", linewidth=1.5)
    axes[0].plot(times, psi_out, label="Outlet Pressure", color="tomato",    linewidth=1.5)
    axes[0].plot(times, dp,      label="ΔP",              color="gray",      linewidth=1.5, linestyle="--")
    axes[0].set_ylabel("Pressure (PSI)")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(True, linestyle="--", alpha=0.5)

    axes[1].plot(times, temp_hx,  label="Plate Temp",  color="darkorange", linewidth=2.0)
    axes[1].plot(times, temp_in,  label="Inlet Temp",  color="steelblue",  linewidth=1.5)
    axes[1].plot(times, temp_out, label="Outlet Temp", color="tomato",     linewidth=1.5)
    axes[1].axhline(y=initial_t, color="red",   linestyle=":", linewidth=1.2, label=f"Start {initial_t:.1f}°C")
    axes[1].axhline(y=final_t,   color="green", linestyle=":", linewidth=1.2, label=f"End {final_t:.1f}°C")
    axes[1].set_ylabel("Temperature (°C)")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, linestyle="--", alpha=0.5)

    axes[2].plot(times, flow_data, label="Flow Rate", color="seagreen", linewidth=1.5)
    axes[2].set_ylabel("Flow (L/min)")
    axes[2].set_xlabel("Time (s)")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].grid(True, linestyle="--", alpha=0.5)

    txt = (f"Initial T_plate : {initial_t:.2f} C\n"
           f"Final T_plate   : {final_t:.2f} C\n"
           f"Total drop      : {initial_t - final_t:.2f} C\n"
           f"Cooling rate    : {cooling_rate:.4f} C/s\n")
    if metrics:
        txt += (f"Q               : {metrics['Q']:.3f} W\n"
                f"R_th            : {metrics['R_th']:.4f} C/W\n"
                f"Efficiency      : {metrics['efficiency']:.2f} W/W")
    fig.text(0.01, 0.01, txt, fontsize=9, family="monospace",
             verticalalignment="bottom",
             bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout(rect=[0, 0.15, 1, 1])
    plt.savefig(PNG_FILE, dpi=150)
    print(f"Graph saved → {PNG_FILE}")
    plt.close(fig)

def write_summary(writer, initial_t, final_t, cooling_rate, metrics):
    writer.writerow([])
    writer.writerow(["── SUMMARY ──"])
    writer.writerow(["metric", "value", "unit"])
    writer.writerow(["initial_plate_temp", f"{initial_t:.2f}",           "C"])
    writer.writerow(["final_plate_temp",   f"{final_t:.2f}",             "C"])
    writer.writerow(["total_drop",         f"{initial_t - final_t:.2f}", "C"])
    writer.writerow(["cooling_rate",       f"{cooling_rate:.4f}",        "C/s"])
    if metrics:
        writer.writerow(["avg_inlet_temp",     f"{metrics['avg_t_in']:.2f}",   "C"])
        writer.writerow(["avg_outlet_temp",    f"{metrics['avg_t_out']:.2f}",  "C"])
        writer.writerow(["avg_flow_rate",      f"{metrics['avg_flow']:.3f}",   "L/min"])
        writer.writerow(["avg_pressure_drop",  f"{metrics['avg_dp_psi']:.3f}", "PSI"])
        writer.writerow(["heat_removed_Q",     f"{metrics['Q']:.3f}",          "W"])
        writer.writerow(["thermal_resistance", f"{metrics['R_th']:.4f}",       "C/W"])
        writer.writerow(["pumping_power",      f"{metrics['P_pump']:.5f}",     "W"])
        writer.writerow(["cooling_efficiency", f"{metrics['efficiency']:.2f}", "W/W"])

# ── MAIN ───────────────────────────────────────────────
print("\n" + "="*52)
print("    COOLING RATE LOGGER")
print("="*52)
print("  Heat plate to desired temp then turn pump on.")
print("  Test starts automatically when flow detected.\n")

csvfile = open(CSV_FILE, "w", newline="")
writer  = csv.writer(csvfile)
writer.writerow(["time_s","psi_in","psi_out","temp_in_C",
                 "temp_out_C","temp_hx_C","flow_LPM","delta_P_psi"])

times_all   = []
psi_in_all  = [];  psi_out_all  = []
temp_in_all = [];  temp_out_all = []
temp_hx_all = [];  flow_all     = []
initial_t_hx = None
log_start_ms = None

try:
    # ── PHASE 1: Wait for pump, display plate temp ────
    while True:
        data = read_line()
        t_hx = data[5]
        fl   = data[6]
        print(f"  T_plate={t_hx:.1f}°C  T_in={data[3]:.1f}°C  "
              f"T_out={data[4]:.1f}°C  Flow={fl:.3f} L/min  — waiting for pump...", end="\r")

        if fl >= FLOW_TRIGGER:
            log_start_ms = data[0]
            initial_t_hx = data[5]
            print(f"\n\n  ✓ Pump on! Flow={fl:.2f} L/min — logging {int(TEST_DURATION)}s\n")
            print(f"  {'Time':>6} | {'T_in':>6} {'T_out':>6} {'T_plate':>7} | "
                  f"{'Flow':>7} | {'ΔP':>6} | {'Drop':>7}")
            print(f"  {'─'*68}")
            break

    # ── PHASE 2: Log for 30 seconds ───────────────────
    while True:
        data   = read_line()
        raw_ms, p1, p2, t1, t2, t3, fl, _ = data
        t      = (raw_ms - log_start_ms) / 1000.0
        dp     = p1 - p2
        drop   = initial_t_hx - t3

        if t <= TEST_DURATION:
            times_all.append(t)
            psi_in_all.append(p1);   psi_out_all.append(p2)
            temp_in_all.append(t1);  temp_out_all.append(t2)
            temp_hx_all.append(t3);  flow_all.append(fl)

            writer.writerow([f"{t:.3f}", f"{p1:.3f}", f"{p2:.3f}",
                             f"{t1:.2f}", f"{t2:.2f}", f"{t3:.2f}",
                             f"{fl:.3f}", f"{dp:.3f}"])
            csvfile.flush()

            print(f"  {t:6.1f}s | {t1:5.1f}°C {t2:5.1f}°C {t3:6.1f}°C | "
                  f"{fl:6.2f} L/m | {dp:5.2f} PSI | {drop:+.2f}°C")
        else:
            final_t_hx   = temp_hx_all[-1]
            total_drop   = initial_t_hx - final_t_hx
            cooling_rate = total_drop / TEST_DURATION

            metrics = calculate_metrics(psi_in_all, psi_out_all,
                                        temp_in_all, temp_out_all,
                                        temp_hx_all, flow_all)

            print(f"\n{'='*52}")
            print(f"  ★  RESULTS  ★")
            print(f"{'='*52}")
            print(f"  Initial plate temp  : {initial_t_hx:.2f} °C")
            print(f"  Final plate temp    : {final_t_hx:.2f} °C")
            print(f"  Total drop          : {total_drop:.2f} °C")
            print(f"  Cooling rate        : {cooling_rate:.4f} °C/s")
            if metrics:
                print(f"  Avg flow rate       : {metrics['avg_flow']:.3f} L/min")
                print(f"  Avg pressure drop   : {metrics['avg_dp_psi']:.3f} PSI")
                print(f"  Heat removed (Q)    : {metrics['Q']:.3f} W")
                print(f"  Thermal resistance  : {metrics['R_th']:.4f} °C/W")
                print(f"  Pumping power       : {metrics['P_pump']:.5f} W")
                print(f"  Cooling efficiency  : {metrics['efficiency']:.2f} W/W")
            print(f"{'='*52}\n")

            write_summary(writer, initial_t_hx, final_t_hx, cooling_rate, metrics)
            csvfile.close()
            save_graph(times_all, psi_in_all, psi_out_all, temp_in_all, temp_out_all,
                       temp_hx_all, flow_all, initial_t_hx, final_t_hx, cooling_rate, metrics)
            print(f"CSV saved  → {CSV_FILE}\n")
            break

except KeyboardInterrupt:
    print("\n\nStopped early.")
    if times_all and initial_t_hx:
        final_t_hx   = temp_hx_all[-1]
        total_drop   = initial_t_hx - final_t_hx
        cooling_rate = total_drop / times_all[-1] if times_all[-1] > 0 else 0
        metrics      = calculate_metrics(psi_in_all, psi_out_all,
                                         temp_in_all, temp_out_all,
                                         temp_hx_all, flow_all)
        write_summary(writer, initial_t_hx, final_t_hx, cooling_rate, metrics)
        save_graph(times_all, psi_in_all, psi_out_all, temp_in_all, temp_out_all,
                   temp_hx_all, flow_all, initial_t_hx, final_t_hx, cooling_rate, metrics)
    csvfile.close()
    print(f"CSV saved  → {CSV_FILE}")
finally:
    ser.close()