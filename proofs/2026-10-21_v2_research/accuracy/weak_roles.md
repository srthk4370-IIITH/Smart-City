# Weak slices on the device (host400 + partial test split)

rows (host400 U test_all, dedup): 1053

water/seen: n=22 pattern 1.00 status 0.82; top pattern errors (gold, pred): []
   status errors (gold, pred): [(('warning', 'normal'), 3), (('sensor_fault', 'critical'), 1)]
   by family: compound 2/2, event 10/10, fault 3/3, routine 3/3, stable 1/1, water_fill 3/3

water/unseen: n=21 pattern 0.52 status 0.62; top pattern errors (gold, pred): [(('dip', 'stable'), 2), (('exponential_increase', 'stable'), 1), (('throttling', 'step_increase'), 1), (('erratic', 'spike'), 1), (('gradual_decrease', 'gradual_increase'), 1), (('oscillation', 'step_increase'), 1), (('spike', 'step_increase'), 1), (('stable', 'gradual_decrease'), 1)]
   status errors (gold, pred): [(('critical', 'normal'), 4), (('sensor_fault', 'normal'), 1), (('normal', 'critical'), 1), (('normal', 'warning'), 1), (('normal', 'sensor_fault'), 1)]
   by family: compound 1/2, event 3/9, fault 1/2, long_drift 2/2, old_shift 1/1, real_longrange 1/1, real_routine 0/1, recurring 1/1, stable 0/1, zero_idle 1/1

water/unseen_sepoct: n=23 pattern 0.74 status 0.70; top pattern errors (gold, pred): [(('oscillation', 'spike'), 1), (('step_decrease', 'gradual_decrease'), 1), (('gradual_increase', 'step_increase'), 1), (('oscillation', 'flatline'), 1), (('dip', 'stable'), 1), (('stable', 'flatline'), 1)]
   status errors (gold, pred): [(('critical', 'normal'), 3), (('normal', 'sensor_fault'), 2), (('critical', 'warning'), 1), (('warning', 'critical'), 1)]
   by family: compound 4/5, event 6/8, fault 2/2, long_drift 1/1, old_shift 1/1, real_longrange 1/1, real_routine 0/1, recurring 1/1, routine 0/1, stable 0/1, zero_idle 1/1

power/seen: n=36 pattern 0.81 status 0.83; top pattern errors (gold, pred): [(('erratic', 'dip'), 2), (('gradual_increase', 'step_increase'), 1), (('stable', 'oscillation'), 1), (('step_increase', 'gradual_increase'), 1), (('oscillation', 'gradual_increase'), 1), (('step_decrease', 'oscillation'), 1)]
   status errors (gold, pred): [(('normal', 'warning'), 5), (('warning', 'normal'), 1)]
   by family: compound 4/4, event 10/13, fault 4/4, long_drift 1/1, old_shift 3/3, real_longrange 1/2, real_routine 2/5, routine 2/2, stable 1/1, zero_idle 1/1

power/unseen: n=31 pattern 0.74 status 0.48; top pattern errors (gold, pred): [(('oscillation', 'stable'), 2), (('gradual_decrease', 'flatline'), 1), (('gradual_decrease', 'spike'), 1), (('dip', 'stable'), 1), (('spike', 'stable'), 1), (('gradual_decrease', 'stable'), 1), (('stable', 'spike'), 1)]
   status errors (gold, pred): [(('warning', 'normal'), 6), (('warning', 'critical'), 4), (('critical', 'normal'), 3), (('normal', 'critical'), 2), (('warning', 'sensor_fault'), 1)]
   by family: compound 5/7, event 7/11, fault 1/1, long_drift 3/3, old_shift 2/2, real_longrange 2/2, real_routine 1/1, routine 2/3, stable 0/1

air_quality/seen: n=356 pattern 0.90 status 0.96; top pattern errors (gold, pred): [(('stable', 'gradual_decrease'), 5), (('gradual_decrease', 'step_decrease'), 3), (('erratic', 'dip'), 2), (('dip', 'stable'), 2), (('erratic', 'spike'), 2), (('gradual_increase', 'stable'), 2), (('stable', 'dip'), 2), (('step_decrease', 'stable'), 1)]
   status errors (gold, pred): [(('sensor_fault', 'normal'), 6), (('normal', 'sensor_fault'), 2), (('normal', 'warning'), 2), (('sensor_fault', 'warning'), 1), (('normal', None), 1), (('sensor_fault', None), 1)]
   by family: compound 20/22, event 118/138, fault 39/46, long_drift 20/21, old_shift 16/17, real_longrange 7/8, real_routine 20/20, recurring 20/20, routine 37/39, stable 23/25

air_quality/unseen: n=184 pattern 0.84 status 0.91; top pattern errors (gold, pred): [(('stable', 'spike'), 5), (('step_increase', 'throttling'), 4), (('stable', 'erratic'), 3), (('dip', 'erratic'), 2), (('stable', 'dip'), 2), (('stable', None), 2), (('erratic', 'dip'), 1), (('step_increase', 'gradual_increase'), 1)]
   status errors (gold, pred): [(('normal', 'sensor_fault'), 5), (('warning', None), 2), (('critical', 'sensor_fault'), 1), (('sensor_fault', 'normal'), 1), (('warning', 'normal'), 1), (('warning', 'critical'), 1)]
   by family: compound 10/11, event 68/82, fault 19/20, long_drift 6/7, old_shift 8/11, real_longrange 3/3, real_routine 10/13, recurring 2/2, routine 15/16, stable 13/19