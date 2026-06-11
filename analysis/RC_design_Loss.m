% PIN-PS Loss-to-Bandwidth Equalizer Simulation
% Input: Maximum Tolerable Insertion Loss
% Output: Achieved Bandwidth and RC Components

clear; clc; close all;

%% 1. Device Parameters (Extracted from CHARGE)
C_F = 0.3471e-12;   % Intrinsic Capacitance (F)
R_F = 10.55e3;      % Parallel Resistance (Ohms)
R_S = 23.31;        % Series Resistance (Ohms) - Assuming you fix the doping!
R_drv = 50;         % Driver Impedance (Ohms)

%% 2. System Bandwidth & Equalizer Design
target_IL_dB = 24.08; % Enter your MAXIMUM allowable insertion loss (e.g., -12 dB)

% Calculate the required Bandwidth Extension Factor (eta) from Loss
eta = 10^(target_IL_dB / 20); 

% Calculate raw system bandwidth
f3dB_raw = 1 / (2 * pi * (R_S + R_drv) * C_F);

% Calculate the Achieved Bandwidth
f_achieved = f3dB_raw * eta;

% Calculate the physical Equalizer components
C_E = C_F / eta;    % Equalizer Capacitance (Eq 11)
R_E = R_F * eta;    % Equalizer Resistance (Eq 12)

%% 3. Frequency Array (10 MHz to 1 THz)
f = logspace(7, 12, 100000); 
w = 2 * pi * f;

%% 4. S21 (Electro-Optic Bandwidth) Calculations
% Raw Device S21
H_raw = 1 ./ (1 + 1i * w .* C_F .* (R_S + R_drv));
S21_raw_abs = 20 * log10(abs(H_raw));

% Equalized System S21
H_eq = (1/eta) ./ (1 + 1i * w .* C_E .* (R_S + R_drv));
S21_eq_abs = 20 * log10(abs(H_eq));
S21_eq_norm = S21_eq_abs - S21_eq_abs(1); 

%% 5. Plotting the S21 Graph
figure('Name', 'Loss-Driven Equalizer Design', 'Color', 'w', 'Position', [100, 100, 800, 500]);

semilogx(f, S21_raw_abs,'Color', 'b', 'LineWidth', 2); hold on;
semilogx(f, S21_eq_abs, 'Color', 'r', 'LineWidth', 2);
semilogx(f, S21_eq_norm, '--','Color', '#c0504d','LineWidth', 1.5); 

yline(-3, 'k:', 'LineWidth', 1.5, 'Label', '-3 dB Bandwidth Limit', 'LabelHorizontalAlignment', 'left');
xline(f3dB_raw, ':', 'color', '#1b3b6f', 'LineWidth', 1);
xline(f_achieved, 'r:', 'LineWidth', 1);

grid on;
xlabel('Frequency (Hz)', 'FontSize', 12, 'FontWeight', 'bold');
ylabel('E-O Response (dB)', 'FontSize', 12, 'FontWeight', 'bold');
legend(sprintf('Raw Device (f_{3dB}=%.2f GHz)',f3dB_raw/1e9), ...
       sprintf('Equalized (f_{3dB}=%.2f GHz, \\eta=%.2f)', f_achieved / 1e9, eta), ...
       'Equalized (Normalized to 0 dB)', ...
       'Location', 'southwest');
xlim([1e7 1e12]); 
ylim([-35 5]);

%% 6. Console Output for INTERCONNECT
fprintf('\n--- Power Budget Analysis ---\n');
fprintf('Maximum Tolerable Loss: %.2f dB\n', target_IL_dB);
fprintf('Calculated Eta: %.2f\n', eta);
fprintf('Raw Device f_3dB: %.2f GHz\n', f3dB_raw / 1e9);
fprintf('ACHIEVED SYSTEM BANDWIDTH: %.2f GHz\n\n', f_achieved / 1e9);

fprintf('--- Required INTERCONNECT Equalizer Values ---\n');
fprintf('Equalizer Resistor (R_E): %.2f kOhms\n', R_E / 1e3);
fprintf('Equalizer Capacitor (C_E): %.4f pF\n', C_E * 1e12);