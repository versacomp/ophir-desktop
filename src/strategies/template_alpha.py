# src/sandbox/template_alpha.py

class CustomAlpha:
    """
    OphirTrade - Blank Alpha Template
    Duplicate this file, rename it to 'alpha.py', and build your strategy.
    """

    STRATEGY_NAME = "Custom Alpha"
    STRATEGY_DESCRIPTION = "Blank template. Implement evaluate() with your quantitative logic."

    def __init__(self):
        self.REQUIRED_BUFFER = 200

    def evaluate(self, raw_candles: list, use_trend: bool = True, use_range: bool = True) -> dict:
        """USER: Write your custom quantitative logic here."""
        return {"action": 0, "confidence": 0.0, "direction": "FLAT", "level": 0.0, "type": "NONE"}