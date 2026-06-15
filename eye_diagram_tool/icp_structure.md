
PS C:\Mac\Home\Desktop\Final_Project\PIN_MZ\PS_Opt_V2\analysis> py .\dump_icp_structure.py
C:\Program Files\Lumerical\v231\api\python\lumapi.py:815: SyntaxWarning: invalid escape sequence '\s'
  message = re.sub('^(Error:)\s(prompt line)\s[0-9]+:', '', str(rvals[2])).strip()

===== mzm_eye_baseline.icp  (14 root elements) =====

[1] LASER
      model                    = ''
      type                     = 'CW Laser'
      prefix                   = 'CWL'
      frequency                = 228849204580152.7
      power                    = 0.001

[2] MZM
      model                    = ''
      type                     = 'Mach-Zehnder Modulator'
      prefix                   = 'MZM'

[3] PD
      model                    = ''
      type                     = 'PIN Photodetector'
      prefix                   = 'PIN'
      load from file           = 0.0
      frequency                = 193100000000000.0
      responsivity             = 1.0

[4] PRBS
      model                    = ''
      type                     = 'PRBS Generator'
      prefix                   = 'PRBS'
      order                    = 8.99859042974533
      bitrate                  = 100000000000.0

[5] PIN_DEV
      model                    = ''
      type                     = 'LP RC Filter'
      prefix                   = 'LPF'
      cutoff frequency         = 6298102054.793679

[6] EYE_1
      model                    = ''
      type                     = 'Eye Diagram'
      prefix                   = 'EYE'
      bitrate                  = 100000000000.0

[7] PD_SCOPE
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[8] TAP_IN
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[9] TAP_OUT
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[10] NRZ_1
      model                    = ''
      type                     = 'NRZ Pulse Generator'
      prefix                   = 'NRZ'
      amplitude                = 0.8310000000000001
      bias                     = 0.0

[11] TIA_1
      model                    = ''
      type                     = 'Transimpedance Amplifier'
      prefix                   = 'TIA'
      cutoff frequency         = 75000000000.0
      order                    = 4.0
      load from file           = 0.0
      s parameters filename    = ''

[12] DC_1
      model                    = ''
      type                     = 'DC Source'
      prefix                   = 'DC'
      amplitude                = -0.43099999999999994

[13] SUM_1
      model                    = ''
      type                     = 'Electrical Adder'
      prefix                   = 'SUM'

[14] OSC_1
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

===== mzm_eye_equalized.icp  (17 root elements) =====

[1] LASER
      model                    = ''
      type                     = 'CW Laser'
      prefix                   = 'CWL'
      frequency                = 228849204580152.7
      power                    = 0.001

[2] MZM
      model                    = ''
      type                     = 'Mach-Zehnder Modulator'
      prefix                   = 'MZM'

[3] PD
      model                    = ''
      type                     = 'PIN Photodetector'
      prefix                   = 'PIN'
      load from file           = 0.0
      frequency                = 193100000000000.0
      responsivity             = 1.0

[4] PRBS
      model                    = ''
      type                     = 'PRBS Generator'
      prefix                   = 'PRBS'
      order                    = 8.99859042974533
      bitrate                  = 100000000000.0

[5] RC_EQ
      model                    = ''
      type                     = 'Electrical N Port S-Parameter'
      prefix                   = 'SPAR'
      load from file           = 1.0
      s parameters filename    = 'C:\\Users\\roie1\\Desktop\\collage\\final_project\\Reports\\eye_rc_interconnect\\eye_rc_interconnect\\rc_equalizer_S21.s2p'

[6] EYE_1
      model                    = ''
      type                     = 'Eye Diagram'
      prefix                   = 'EYE'
      bitrate                  = 100000000000.0

[7] TAP_IN
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[8] TAP_OUT
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[9] AMP_1
      model                    = ''
      type                     = 'Electrical Amplifier'
      prefix                   = 'AMP'
      gain                     = 24.08

[10] NRZ_1
      model                    = ''
      type                     = 'NRZ Pulse Generator'
      prefix                   = 'NRZ'
      amplitude                = 0.8619999999999999
      bias                     = 0.0

[11] TIA_1
      model                    = ''
      type                     = 'Transimpedance Amplifier'
      prefix                   = 'TIA'
      cutoff frequency         = 75000000000.0
      order                    = 4.0
      load from file           = 0.0
      s parameters filename    = ''

[12] OSC_1
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[13] OSC_2
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[14] PD_SCOPE
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'

[15] LPF_1
      model                    = ''
      type                     = 'LP RC Filter'
      prefix                   = 'LPF'
      cutoff frequency         = 6298102054.793679

[16] OOSC_1
      model                    = ''
      type                     = 'Optical Oscilloscope'
      prefix                   = 'OOSC'
      frequency                = 193100000000000.0

[17] OSC_4
      model                    = ''
      type                     = 'Oscilloscope'
      prefix                   = 'OSC'
