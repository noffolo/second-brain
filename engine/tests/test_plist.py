from engine.plist_generator import parse_cron_to_launchd

def test_parse_seconds():
    snippet = parse_cron_to_launchd("1200")
    assert "<key>StartInterval</key>" in snippet
    assert "<integer>1200</integer>" in snippet

def test_parse_hourly_cron():
    snippet = parse_cron_to_launchd("0 * * * *")
    assert "<key>StartCalendarInterval</key>" in snippet
    assert "<key>Minute</key>" in snippet
    assert "<integer>0</integer>" in snippet
    assert "Hour" not in snippet
    assert "Weekday" not in snippet

def test_parse_weekly_cron():
    snippet = parse_cron_to_launchd("0 21 * * 0")
    assert "<key>StartCalendarInterval</key>" in snippet
    assert "<key>Minute</key>" in snippet
    assert "<integer>0</integer>" in snippet
    assert "<key>Hour</key>" in snippet
    assert "<integer>21</integer>" in snippet
    assert "<key>Weekday</key>" in snippet
    assert "<integer>0</integer>" in snippet

def test_parse_invalid_cron():
    # Invalid pattern should fallback to default 3600 seconds interval
    snippet = parse_cron_to_launchd("invalid cron")
    assert "<key>StartInterval</key>" in snippet
    assert "<integer>3600</integer>" in snippet
