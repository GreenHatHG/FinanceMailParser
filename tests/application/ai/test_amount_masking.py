from financemailparser.application.ai.amount_masking import (
    AmountMasker,
    restore_beancount_amounts,
)


def test_masks_posting_amount_only():
    text = (
        '2026-01-01 * "Coffee"\n'
        "  Expenses:Food  -12.34 USD ; comment 99 USD\n"
        "  Assets:Cash\n"
    )
    masker = AmountMasker(run_id="r", start_seq=1)
    masked = masker.mask_text(text)

    assert "-__AMT_r_000001__ USD" in masked
    assert "comment 99 USD" in masked  # 注释内容应保持原样（不脱敏）
    assert len(masker.mapping) == 1  # 只应脱敏 posting 金额
    assert masker.mapping.get("__AMT_r_000001__") == "12.34"

    restored, rep = restore_beancount_amounts(masked, masker.mapping)
    assert restored == text
    assert rep.tokens_replaced == 1


def test_masks_price_directive_without_touching_date():
    text = "2026-01-02 price BTC 42,000 USD ; 1 USD\n"
    masker = AmountMasker(run_id="r", start_seq=1)
    masked = masker.mask_text(text)

    assert masked.startswith("2026-01-02 price BTC ")
    assert "__AMT_r_000001__ USD" in masked
    assert "2026-01-__AMT_" not in masked
    assert masker.mapping.get("__AMT_r_000001__") == "42,000"

    restored, _rep = restore_beancount_amounts(masked, masker.mapping)
    assert restored == text


def test_masks_multiple_amounts_same_line():
    text = '2026-01-03 * "X"\n  Assets:Broker  0.5 BTC @ 42000 USD\n'
    masker = AmountMasker(run_id="r", start_seq=1)
    masked = masker.mask_text(text)

    assert "__AMT_r_000001__ BTC @ __AMT_r_000002__ USD" in masked
    assert masker.mapping.get("__AMT_r_000001__") == "0.5"
    assert masker.mapping.get("__AMT_r_000002__") == "42000"

    restored, _rep = restore_beancount_amounts(masked, masker.mapping)
    assert restored == text


def test_masks_scientific_notation_when_lexer_marks_exponent_error():
    text = '2026-01-04 * "Y"\n  Expenses:Fees  1.2e-3 USD\n'
    masker = AmountMasker(run_id="r", start_seq=1)
    masked = masker.mask_text(text)

    assert "__AMT_r_000001__ USD" in masked
    assert masker.mapping.get("__AMT_r_000001__") == "1.2e-3"

    restored, _rep = restore_beancount_amounts(masked, masker.mapping)
    assert restored == text
