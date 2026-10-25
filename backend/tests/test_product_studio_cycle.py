from app.product_studio import assess_performance, next_experiment

def test_card_review_requires_sample():
    r=assess_performance({"views":12,"orders":0})
    assert r["decision"]=="insufficient_data" and not r["should_optimize"]

def test_card_review_optimizes_low_conversion():
    r=assess_performance({"views":100,"orders":0})
    assert r["decision"]=="optimize" and r["should_optimize"]

def test_card_review_rolls_back_worse_version():
    r=assess_performance({"views":100,"orders":1},{"views":100,"orders":4})
    assert r["decision"]=="rollback" and r["delta_percent"] < 0

def test_card_review_keeps_better_version():
    r=assess_performance({"views":100,"orders":6},{"views":100,"orders":4})
    assert r["decision"]=="keep" and not r["should_optimize"]

def test_experiment_changes_one_layer_at_a_time():
    assert next_experiment(1)["change"]=="main_image"
    assert next_experiment(2)["change"]=="visuals"
    assert next_experiment(3)["change"]=="content"
