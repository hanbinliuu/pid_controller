"""
测试单个文件的整定和评估
"""
import os
from pid_simulation_evaluation_exp import main

# 测试response_1762741206598.json
TEST_FILE = "/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/data_simulation/zhongkong/response_1762741206598.json"
OUTPUT_DIR = "/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/core/algo/system_tuning/tests/simulation_tests/output_test_single"

if os.path.exists(TEST_FILE):
    print("="*80)
    print("测试单个文件：response_1762741206598.json")
    print("="*80)
    print(f"测试文件: {TEST_FILE}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("="*80)
    
    # 删除旧图片（如果存在）
    old_img = os.path.join(OUTPUT_DIR, "response_1762741206598_pid_tuning_evaluation.png")
    if os.path.exists(old_img):
        os.remove(old_img)
        print(f"✅ 已删除旧图片")
    
    main(
        json_file_path=TEST_FILE,
        output_dir=OUTPUT_DIR,
        verbose=True,
        show_plot=False,
        enable_evaluation=True
    )
    
    print("\n" + "="*80)
    print("测试完成！")
    print("="*80)
    print(f"\n请查看图片: {old_img}")
    print("检查整定段标注是否在2512-3599之间")
    print("="*80)
else:
    print(f"❌ 测试文件不存在: {TEST_FILE}")
