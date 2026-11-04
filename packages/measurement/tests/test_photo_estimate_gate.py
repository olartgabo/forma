"""A #177 photo estimate is shown as an estimate and never satisfies a question."""

from measurement_inputs import UNKNOWN, tape
from test_decide import decide

from forma_domain import models as m


def photo(value):
    return m.Measurement(
        value=value, unit="mm", source="photo_estimate", confirmed=False
    )


def test_photo_estimate_sizes_are_still_asked_as_unconfirmed():
    stock = m.Stock(
        id="sheet-a",
        kind="sheet",
        material="cardboard",
        condition="usable",
        width_mm=photo(300),
        height_mm=photo(600),
        thickness_mm=m.Measurement(
            value=2, unit="mm", source="user_ruler", confirmed=True
        ),
        remaining_length_mm=UNKNOWN,
    )
    decision = decide((stock, tape()))
    assert decision.outcome == "question"
    current = decision.question.current
    assert current.source == "photo_estimate" and current.confirmed is False
    assert decision.question.target.stock_id == "sheet-a"
    assert decision.design.status != "candidates_found"
