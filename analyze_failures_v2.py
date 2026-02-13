
import re

log_file = 'full_log_v311_final_check.txt'

with open(log_file, 'r') as f:
    content = f.read()

scenarios = content.split('Scenario ')
failed_scenarios = []

print(f"Total scenarios found: {len(scenarios)}")

for scenario in scenarios:
    if not scenario.strip():
        continue
        
    lines = scenario.split('\n')
    name = lines[0].strip()
    
    # Extract loop type
    loop_type = "unknown"
    if "Type: " in scenario:
        match = re.search(r"Type:\s+(\w+)", scenario)
        if match:
            loop_type = match.group(1)
    
    # Check for failure
    is_failed = "稳态(真实参数): ❌" in scenario
    
    if is_failed and loop_type in ['pressure', 'level']:
        # Extract PID params
        pb = "N/A"
        ti = "N/A"
        td = "N/A"
        
        # Match "PB = 123.45%"
        pb_match = re.search(r"PB\s*=\s*([\d\.]+)%", scenario)
        if pb_match:
            pb = pb_match.group(1)
            
        ti_match = re.search(r"TI\s*=\s*([\d\.]+)s", scenario)
        if ti_match:
            ti = ti_match.group(1)

        td_match = re.search(r"TD\s*=\s*([\d\.]+)s", scenario)
        if td_match:
            td = td_match.group(1)
            
        print(f"FAILED: {loop_type} - {name}")
        print(f"  Params: PB={pb}, Ti={ti}, Td={td}")
        
