import random

STRATIFIED_HIGH_RATIO = 0.50
STRATIFIED_MEDIUM_RATIO = 0.20

Z_SCORE = {
    90: 1.645,
    95: 1.96,
    99: 2.575,
}


def _rng(seed=None):
    return random.Random(seed)


def _dedupe_preserve_order(values):
    seen = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def calculate_sample_size(
    confidence_level,
    expected_error_rate,
    population_size,
    tolerable_error_rate=None,
    tolerable_misstatement=None,
    population_value=None,
):
    z = Z_SCORE.get(int(confidence_level), 1.96)
    p = expected_error_rate / 100.0
    if tolerable_misstatement is not None and population_value and population_value > 0:
        e = tolerable_misstatement / population_value
    else:
        e = (tolerable_error_rate or 0) / 100.0
    if e <= 0:
        return max(15, min(population_size, 15))
    n = (z * z * p * (1 - p)) / (e * e)
    n = int(round(n))
    if n < 15:
        n = 15
    if n > population_size:
        n = population_size
    return n


def random_sampling(population_ids, sample_size, seed=None):
    if sample_size <= 0 or not population_ids:
        return []
    generator = _rng(seed)
    if sample_size >= len(population_ids):
        return list(population_ids)
    return generator.sample(population_ids, sample_size)


def systematic_sampling(population_ids, sample_size, seed=None):
    if sample_size <= 0 or len(population_ids) == 0:
        return []
    ordered_ids = list(population_ids)
    if sample_size >= len(ordered_ids):
        return ordered_ids
    generator = _rng(seed)
    interval = len(ordered_ids) / sample_size
    start = generator.uniform(0, interval)
    selected = []
    for step in range(sample_size):
        position = min(int(start + (step * interval)), len(ordered_ids) - 1)
        selected.append(ordered_ids[position])
    selected = _dedupe_preserve_order(selected)
    if len(selected) < sample_size:
        fill = [pid for pid in ordered_ids if pid not in set(selected)]
        selected.extend(fill[: sample_size - len(selected)])
    return selected


def mus_sampling(population_items, sample_size, seed=None):
    if sample_size <= 0 or len(population_items) == 0:
        return []
    positive_items = [item for item in population_items if (item.get("amount") or 0) > 0]
    if not positive_items:
        return []
    if sample_size >= len(positive_items):
        return [item["id"] for item in positive_items]
    generator = _rng(seed)
    total_value = sum(item["amount"] for item in positive_items)
    interval = total_value / sample_size
    start = generator.uniform(0, interval)
    selected = []
    cumulative = 0.0
    target = start
    for item in positive_items:
        cumulative += item["amount"]
        while cumulative >= target and len(selected) < sample_size:
            selected.append(item["id"])
            target += interval
    if len(selected) < sample_size:
        selected.extend([item["id"] for item in positive_items][: sample_size - len(selected)])
    selected = _dedupe_preserve_order(selected)
    if len(selected) < sample_size:
        remaining = [item["id"] for item in positive_items if item["id"] not in set(selected)]
        selected.extend(remaining[: sample_size - len(selected)])
    return selected


def classify_stratum(amount, materiality):
    if materiality <= 0:
        return "unstratified"
    if amount >= STRATIFIED_HIGH_RATIO * materiality:
        return "high"
    if amount >= STRATIFIED_MEDIUM_RATIO * materiality:
        return "medium"
    return "low"


def _allocate_stratified_counts(strata_buckets, sample_size):
    non_empty = [(name, items) for name, items in strata_buckets if items]
    counts = {name: 0 for name, _ in strata_buckets}
    total_items = sum(len(items) for _, items in non_empty)
    if sample_size <= 0 or total_items == 0:
        return counts
    if sample_size >= total_items:
        for name, items in non_empty:
            counts[name] = len(items)
        return counts

    values = {name: sum(item["amount"] for item in items) for name, items in non_empty}
    capacities = {name: len(items) for name, items in non_empty}

    if sample_size < len(non_empty):
        ranked = sorted(non_empty, key=lambda entry: (values[entry[0]], -["high", "medium", "low"].index(entry[0])), reverse=True)
        for name, _ in ranked[:sample_size]:
            counts[name] = 1
        return counts

    for name, _ in non_empty:
        counts[name] = 1

    remaining = sample_size - len(non_empty)
    total_value = sum(values.values())
    provisional = []
    allocated = 0
    for name, _ in non_empty:
        exact = (remaining * values[name] / total_value) if total_value > 0 else 0
        add = min(int(exact), capacities[name] - counts[name])
        counts[name] += add
        allocated += add
        provisional.append((exact - int(exact), name))

    leftover = remaining - allocated
    for _, name in sorted(provisional, key=lambda entry: (entry[0], -["high", "medium", "low"].index(entry[1])), reverse=True):
        if leftover <= 0:
            break
        if counts[name] >= capacities[name]:
            continue
        counts[name] += 1
        leftover -= 1

    if leftover > 0:
        for name, _ in non_empty:
            while leftover > 0 and counts[name] < capacities[name]:
                counts[name] += 1
                leftover -= 1

    return counts


def stratified_sampling(population_items, sample_size, materiality, seed=None):
    high = []
    medium = []
    low = []
    strata_map = {}
    for item in population_items:
        label = classify_stratum(item["amount"], materiality)
        strata_map[item["id"]] = label
        if label == "high":
            high.append(item)
        elif label == "medium":
            medium.append(item)
        else:
            low.append(item)
    selected = []
    generator = _rng(seed)
    counts = _allocate_stratified_counts([
        ("high", high),
        ("medium", medium),
        ("low", low),
    ], sample_size)
    for name, stratum in (("high", high), ("medium", medium), ("low", low)):
        sub_count = counts.get(name, 0)
        if sub_count <= 0:
            continue
        ids = [item["id"] for item in stratum]
        if sub_count >= len(ids):
            selected.extend(ids)
        else:
            selected.extend(generator.sample(ids, sub_count))
    return _dedupe_preserve_order(selected), strata_map


def judgemental_sampling(population_ids, manual_ids):
    allowed = set(population_ids)
    return _dedupe_preserve_order(pid for pid in manual_ids if pid in allowed)


def build_sample_output(
    population_items,
    selected_ids,
    performance_materiality,
    clearly_trivial_threshold,
    auto_high_value_ids=None,
    strata_map=None,
):
    outputs = []
    items_by_id = {item["id"]: item for item in population_items}
    seen = set()
    auto_high_value_ids = set(auto_high_value_ids or [])
    strata_map = strata_map or {}
    combined_ids = list(selected_ids) + [hid for hid in auto_high_value_ids if hid not in selected_ids]
    for pid in combined_ids:
        if pid in seen:
            continue
        seen.add(pid)
        item = items_by_id.get(pid)
        if not item:
            continue
        amount = item["amount"]
        is_high_value = amount > performance_materiality if performance_materiality > 0 else False
        is_trivial = amount < clearly_trivial_threshold if clearly_trivial_threshold > 0 else False
        reason = "high_value_auto" if pid in auto_high_value_ids and pid not in selected_ids else "sample"
        outputs.append({
            "population_id": pid,
            "is_high_value": is_high_value,
            "is_trivial": is_trivial,
            "stratum": strata_map.get(pid),
            "selected_reason": reason,
        })
    return outputs
