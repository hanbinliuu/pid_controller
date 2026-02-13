import re

log_file = 'full_log_v311_final_check.txt'

with open(log_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Split by scene header "场景 X/121"
scenarios = re.split(r'场景\s+\d+/\d+:', content)

print(f"Total scenarios found: {len(scenarios)}")

for i, scenario in enumerate(scenarios):
    if i == 0: continue # Skip prologue
    
    # Extract name
    lines = scenario.strip().split('\n')
    name_line = lines[0].strip()
    
    # Extract loop type
    loop_type = "unknown"
    type_match = re.search(r"Step 0.5: 回路类型（外部指定:\s*(\w+)", scenario)
    if type_match:
        loop_type = type_match.group(1).lower()
    else:
        # Fallback for loop type if not found
        type_match_2 = re.search(r"Loop Type:\s*(\w+)", scenario, re.IGNORECASE)
        if type_match_2:
            loop_type = type_match_2.group(1).lower()

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
        
        # Extract Ts
        ts = "N/A"
        ts_match = re.search(r"稳态\(真实参数\): ❌ .*?\(Ts=(.*?)s\)", scenario)
        if ts_match:
            ts = ts_match.group(1)
            
        print(f"FAILED: [{loop_type}] {name_line}")
        print(f"  Params: PB={pb}%, Ti={ti}s, Td={td}s")
        print(f"  Ts: {ts}s (Limit is usually 300s or 600s)")
        print("-" * 40)
