import numpy as np
from server.processing.pipeline import CSIPipeline


def test_pipeline_stream_alignment():
    """
    Test that CSIPipeline.sync_and_align_streams aligns two node streams with small timestamp drift.
    """
    pipeline = CSIPipeline()

    # Generate Node 1001 stream frames (every 10ms, e.g. 0, 10000, 20000 us)
    frames_1001 = [
        {
            "timestamp_us": i * 10000,
            "rssi": -45,
            "amplitudes": ",".join(["50"] * 64),
            "phases": ",".join(["10"] * 64),
        }
        for i in range(10)
    ]

    # Generate Node 1002 stream frames with 3ms drift (e.g. 3000, 13000, 23000 us)
    frames_1002 = [
        {
            "timestamp_us": i * 10000 + 3000,
            "rssi": -52,
            "amplitudes": ",".join(["40"] * 64),
            "phases": ",".join(["20"] * 64),
        }
        for i in range(10)
    ]

    raw_node_data = {1001: frames_1001, 1002: frames_1002}

    aligned_df = pipeline.sync_and_align_streams(raw_node_data)

    # Since drift (3ms) is within the 10ms tolerance, all 10 frames should align successfully
    assert not aligned_df.empty
    assert len(aligned_df) == 10

    # Verify both node values exist in the columns of the aligned DataFrame
    assert "node_1001_amp" in aligned_df.columns
    assert "node_1002_amp" in aligned_df.columns

    # Check that amplitude lists are loaded as arrays
    assert isinstance(aligned_df["node_1001_amp"].iloc[0], np.ndarray)
    assert len(aligned_df["node_1001_amp"].iloc[0]) == 64
