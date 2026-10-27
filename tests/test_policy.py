from datetime import date

from core import policy as p

MON, WED = date(2026, 10, 19), date(2026, 10, 21)


def dets(**kw):
    return [{"label": k, "conf": v} for k, v in kw.items()]


def test_wash_day_schedule():
    assert p.is_wash_day(WED) and not p.is_wash_day(MON)
    assert p.get_active_profile(WED).name == "Wash Day"


def test_uniform_and_lanyard_pass_every_day():
    for day in (MON, WED):
        ev = p.evaluate_compliance(dets(uniform=0.95, id_lanyard=0.9), day)
        assert ev.compliant and ev.action == p.ACTION_AUTO_PASS


def test_civilian_wear_only_on_wash_day():
    d = dets(civilian_wear=0.95, id_lanyard=0.9)
    assert p.evaluate_compliance(d, MON).violations == [p.V_CIVILIAN_ON_UNIFORM_DAY]
    assert p.evaluate_compliance(d, WED).compliant


def test_lanyard_always_required():
    for day in (MON, WED):
        assert p.V_NO_LANYARD in p.evaluate_compliance(dets(civilian_wear=0.95), day).violations
        assert p.V_NO_LANYARD in p.evaluate_compliance(dets(uniform=0.95), day).violations


def test_all_violations_reported_together():
    ev = p.evaluate_compliance(dets(civilian_wear=0.9), MON)
    assert ev.violation_type == "Civilian Wear on Uniform Day, No Lanyard"


def test_low_confidence_goes_to_queue():
    ev = p.evaluate_compliance(dets(uniform=0.6, id_lanyard=0.9), MON)
    assert ev.status == p.STATUS_LOW_CONFIDENCE and ev.action == p.ACTION_FLAG_QUEUE


def test_empty_or_weak_frames_do_nothing():
    assert p.evaluate_compliance([], MON).action == p.ACTION_NONE
    assert p.evaluate_compliance(dets(uniform=0.2, id_lanyard=0.2), MON).action == p.ACTION_NONE
