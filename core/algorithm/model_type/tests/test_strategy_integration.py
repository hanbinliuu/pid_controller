
import unittest
import numpy as np
from core.algorithm.model_type.tuning.oscillation_tuner import OscillationTuner
from core.algorithm.model_type.tuning.pid_calculator import PIDCalculator
from core.algorithm.model_type.simulation.simulator import ModelSimulator
from core.algorithm.model_type.config import Config

class TestStrategyIntegration(unittest.TestCase):
    def setUp(self):
        self.pid_calc = PIDCalculator()
        self.simulator = ModelSimulator()
        # Mock LLM client is not needed for this test as we are testing rule-based logic
        # Relax pb_max to avoid capping results during testing
        self.original_config = Config.OSCILLATION_TUNING.copy()
        Config.OSCILLATION_TUNING['pb_max'] = 10000.0
        # Reduce base PB calculation so it fits under the hardcoded 600.0 cap
        Config.OSCILLATION_TUNING['pb_from_k_factor'] = 0.05 
        Config.OSCILLATION_TUNING['kp_from_ku_factor'] = 1.0 # pb_from_Ku = 100/1.0 = 100


    def tearDown(self):
        Config.OSCILLATION_TUNING = self.original_config

    def test_flow_loop_high_gain_logic(self):
        """Verify Flow loop logic for K > 6"""
        # 1. Create tuner for FLOW loop
        tuner = OscillationTuner(self.pid_calc, self.simulator, verbose=False, loop_type='flow')
        
        # 2. Get params for High Gain (K=8.0)
        # Based on current logic: factor = 1.0 + (8.0 - 6.0) * 0.4 = 1.8
        # Base PB calculation involves other factors, so we compare relative to a neutral case or check logs/values
        # Easier: check if the calculated PB clearly reflects the boost compared to default loop type
        
        Pu = 10.0
        Ku = 1.0
        K_approx = 8.0 # High gain > 6.0
        
        # Calculate with Flow loop
        params_flow = tuner._get_conservative_pid_params(Pu, Ku, K_approx=K_approx)
        pb_flow = params_flow['pb']
        
        # Calculate with Default loop (change loop type)
        tuner_default = OscillationTuner(self.pid_calc, self.simulator, verbose=False, loop_type='default')
        params_default = tuner_default._get_conservative_pid_params(Pu, Ku, K_approx=K_approx)
        pb_default = params_default['pb']
        
        print(f"Flow PB (K=8): {pb_flow}, Default PB (K=8): {pb_default}")
        
        # Flow PB should be significantly higher (~1.8x, but base logic also has K>4 factor)
        # Both hit K>4 factor. Flow has EXTRA K>6 factor.
        self.assertGreater(pb_flow, pb_default)
        ratio = pb_flow / pb_default
        self.assertAlmostEqual(ratio, 1.8, delta=0.2) # Allow some tolerance

    def test_level_loop_slow_system_logic(self):
        """Verify Level loop logic for Pu > 100"""
        # 1. Create tuner for LEVEL loop
        tuner = OscillationTuner(self.pid_calc, self.simulator, verbose=False, loop_type='level')
        
        # 2. Get params for Slow System (Pu=140)
        # Logic: factor = 1.0 + (140 - 100) / 100 = 1.4
        Pu = 140.0
        Ku = 1.0
        K_approx = 1.0
        
        params_level = tuner._get_conservative_pid_params(Pu, Ku, K_approx=K_approx)
        pb_level = params_level['pb']
        
        # Default loop
        tuner_default = OscillationTuner(self.pid_calc, self.simulator, verbose=False, loop_type='default')
        params_default = tuner_default._get_conservative_pid_params(Pu, Ku, K_approx=K_approx)
        pb_default = params_default['pb']
        
        print(f"Level PB (Pu=140): {pb_level}, Default PB (Pu=140): {pb_default}")
        
        self.assertGreater(pb_level, pb_default)
        ratio = pb_level / pb_default
        self.assertAlmostEqual(ratio, 1.4, delta=0.2)

if __name__ == '__main__':
    unittest.main()
