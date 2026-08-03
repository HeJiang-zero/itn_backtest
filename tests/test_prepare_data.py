from pathlib import Path

import pyarrow.parquet as pq

from itn_backtest.config import load_config
from itn_backtest.prepare_data import prepare_data


HEADER = "Req Sent (UTC),Resp Recv (UTC),RTT (ms),HTTP Status,Symbol,xStock Symbol,xStocks Price (USD),Secs Since Price Change,Stock Feed,Bid,Ask,Quote Age (s),Quote Stale,BIDSIZE,ASKSIZE\n"
ROW = "2026-07-28T13:30:00.000Z,2026-07-28T13:30:00.100Z,100,200,AAPL,AAPLx,100.0,0,NB,101.0,101.1,0.1,false,10,20\n"


def test_prepare_writes_normalized_parquet_and_manifest(tmp_path: Path):
    source = tmp_path / "data"
    source.mkdir()
    (source / "xstocks_log_2026-07-28.csv").write_text(HEADER + ROW, encoding="utf-8")
    curated = tmp_path / "curated"
    manifest = prepare_data(source, curated, load_config())
    assert manifest["rows"] == 1
    table = pq.ParquetFile(curated / "xstocks_log_2026-07-28.parquet").read()
    assert table.num_rows == 1
    assert table.to_pylist()[0]["source_row_id"].endswith(":2")
