
import re

log_file = 'full_log_v311_final_check.txt'

try:
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by scenario separator
    # The separator is a long line of dashes or equals
    # Let's split by "Scenario " at the start of a line
    scenarios = re.split(r'\nScenario ', content)
    
    print(f"Total scenarios found: {len(scenarios)}")
    
    failed_scenarios = []
    
    for i, scenario in enumerate(scenarios):
        if i == 0: continue # Skip prologue
        
        # Re-add "Scenario " prefix if it was consumed
        scenario_text = "Scenario " + scenario
        
        # Extract name
        lines = scenario.split('\n')
        name_line = lines[0].strip()
        
        # Extract loop type
        loop_type = "unknown"
        type_match = re.search(r"Loop Type:\s*(\w+)", scenario, re.IGNORECASE)
        if type_match:
            loop_type = type_match.group(1).lower()
        else:
            # Try step 0.5
            type_match_step = re.search(r"Step 0.5: 回路类型（外部指定:\s*(\w+)", scenario)
            if type_match_step:
                loop_type = type_match_step.group(1).lower()
                
        # Check for failure
        is_failed = "稳态(真实参数): ❌" in scenario
        
        if is_failed and loop_type in ['pressure', 'level']:
            # Extract PID params
            pb = "N/A"
            ti = "N/A"
            td = "N/A"
            
            pb_match = re.search(r"PB\s*=\s*([\d\.]+)%", scenario)
            if pb_match:
                pb = pb_match.group(1)
                
            ti_match = re.search(r"TI\s*=\s*([\d\.]+)s", scenario)
            if ti_match:
                ti = ti_match.group(1)
    
            td_match = re.search(r"TD\s*=\s*([\d\.]+)s", scenario)
            if td_match:
                td = td_match.group(1)
            
            # Extract Ts if available (it will be N/A or > limit)
            ts = "N/A"
            ts_match = re.search(r"稳态\(真实参数\): ❌ .*?\(Ts=(.*?)s\)", scenario)
            if ts_match:
                ts = ts_match.group(1)
                
            print(f"FAILED: [{loop_type}] {name_line}")
            print(f"  Params: PB={pb}%, Ti={ti}s, Td={td}s")
            print(f"  Ts: {ts}s")
            print("-" * 40)

except Exception as e:
    print(f"Error: {e}")
