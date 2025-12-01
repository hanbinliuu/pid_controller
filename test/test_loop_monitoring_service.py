from api.services.loop_monitoring_service import LoopMonitoringService


def main():
    result = LoopMonitoringService.calculate_performance_status("/pid_zd/e7fd8af67d3d472ba6c8478eeb692af6")
    print(result)

if __name__ == "__main__":
    main()