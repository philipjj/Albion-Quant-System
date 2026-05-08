"""
Tests for Hermes Orchestrator.
"""
from app.agents.hermes.orchestrator import HermesOrchestrator

def test_hermes_orchestrator():
    orchestrator = HermesOrchestrator()
    summary = orchestrator.run_daily_summary()
    assert "Hermes Daily Summary" in summary
    
    analysis = orchestrator.analyze_signal("test_signal")
    assert "Hermes Analysis" in analysis
