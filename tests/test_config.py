from itn_backtest.config import load_config


def test_timeline_delays_match_config_contract():
    config = load_config()
    assert config.stock_arrival_delay_ns == 60_000_000
    assert config.stock_report_delay_ns == 50_000_000
    assert config.rfq_execution_delay_ns == 1_620_000_000
    assert config.token_received_delay_ns == 1_620_000_000
    assert config.redeem_complete_delay_ns == 3_100_000_000
    assert config.stock_qty == 10.0
