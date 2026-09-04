"""Covers the conversation-state / intent-update engine: a later turn
must correctly replace or refine the search intent instead of the whole
message thread being concatenated and re-parsed (which let an earlier
"smartphone" turn beat a later "compare laptops" turn -- the original bug
report this module fixes). Mirrors the spec's TEST 1-11 list plus a
couple of classifier edge cases found while building it."""


def chat(client, messages_so_far, new_message):
    messages_so_far.append({"role": "user", "content": new_message})
    response = client.post("/assistant/chat", json={"messages": list(messages_so_far)})
    assert response.status_code == 200, response.text
    body = response.json()
    messages_so_far.append({"role": "assistant", "content": body["reply"]})
    return body


# TEST 1: smartphone -> laptop. New results are laptops only.
def test_category_switch_replaces_results_not_merges(client):
    messages = []
    first = chat(client, messages, "Find a smartphone under 50000 with a good camera")
    assert first["intent"]["category"] == "smartphones"
    assert all(s["product"]["category"] == "smartphones" for s in first["suggestions"])

    second = chat(client, messages, "Compare laptops under 65000 with 16GB RAM")
    assert second["intent"]["category"] == "laptops"
    assert second["intent"]["max_budget"] == 65000
    assert second["suggestions"], second
    assert all(s["product"]["category"] == "laptops" for s in second["suggestions"])
    # The literal bug report: the old smartphone results must not survive.
    assert not any(s["product"]["category"] == "smartphones" for s in second["suggestions"])


# TEST 2: budget 50000 -> 65000. New budget = 65000, category untouched.
def test_budget_correction_replaces_only_the_budget(client):
    messages = []
    first = chat(client, messages, "Find phones under 50000")
    assert first["intent"]["max_budget"] == 50000

    second = chat(client, messages, "Under 65000")
    assert second["intent"]["category"] == "smartphones"
    assert second["intent"]["max_budget"] == 65000


# TEST 3: Samsung -> Google. Samsung is removed, not merged.
def test_brand_swap_replaces_the_brand(client):
    messages = []
    first = chat(client, messages, "Find Samsung phones under 50000")
    assert first["intent"]["brand"] == "Samsung"

    second = chat(client, messages, "Actually show me Google phones")
    assert second["intent"]["brand"] == "Google"
    assert second["intent"]["category"] == "smartphones"
    assert second["intent"]["max_budget"] == 50000
    assert all(s["product"]["brand"] != "Samsung" for s in second["suggestions"])


# TEST 4: laptop -> "16GB RAM". Category stays, RAM preference is added.
def test_refinement_adds_a_constraint_without_dropping_category(client):
    messages = []
    first = chat(client, messages, "Find laptops under 70000")
    assert first["intent"]["category"] == "laptops"

    second = chat(client, messages, "16GB RAM")
    assert second["intent"]["category"] == "laptops"
    assert second["intent"]["max_budget"] == 70000
    assert any("RAM" in pref.upper() for pref in second["intent"]["preferences"])


# A second REFINE_SEARCH example from the spec: adding a color constraint
# on top of an existing brand+budget+category search, without losing any
# of them. (Also a regression test for a fuzzy-match bug found while
# building this: "blue" was incorrectly typo-corrected to "bluetooth",
# which then mis-inferred the category as smartwatches.)
def test_color_refinement_keeps_brand_budget_and_category(client):
    messages = []
    chat(client, messages, "Find Samsung phones under 50000")
    second = chat(client, messages, "Only blue ones")

    assert second["intent"]["category"] == "smartphones"
    assert second["intent"]["brand"] == "Samsung"
    assert second["intent"]["max_budget"] == 50000
    assert second["intent"]["color"] == "blue"
    assert second["suggestions"]
    assert all(s["product"]["color"] == "blue" for s in second["suggestions"])


# TEST 5: existing results -> "second one". Correct product_id resolved.
def test_ordinal_reference_resolves_against_current_candidates(client):
    messages = []
    first = chat(client, messages, "Find headphones under 6000")
    assert len(first["suggestions"]) >= 2
    second_product_id = first["suggestions"][1]["product"]["product_id"]

    second = chat(client, messages, "I want the second one")
    assert len(second["suggestions"]) == 1
    assert second["suggestions"][0]["product"]["product_id"] == second_product_id


# TEST 6: existing results -> "compare first two". Only those two.
def test_compare_first_two_uses_only_the_current_candidates(client):
    messages = []
    first = chat(client, messages, "Find headphones under 6000")
    expected_ids = {s["product"]["product_id"] for s in first["suggestions"][:2]}

    second = chat(client, messages, "Compare the first two")
    assert {s["product"]["product_id"] for s in second["suggestions"]} == expected_ids


# TEST 7: new search clears the old candidate set (not just adds to it).
def test_new_search_clears_old_candidates(client):
    messages = []
    chat(client, messages, "Find headphones under 6000")
    second = chat(client, messages, "Now show me cameras under 70000")

    assert second["intent"]["category"] == "cameras"
    ids = {s["product"]["product_id"] for s in second["suggestions"]}
    assert ids  # fresh candidates exist
    assert all(s["product"]["category"] == "cameras" for s in second["suggestions"])


# TEST 8: new search followed by a purchase reference must resolve
# against the NEW candidate set, never the old one.
def test_purchase_reference_after_new_search_uses_new_candidates(client):
    messages = []
    chat(client, messages, "Find phones under 50000")
    laptops = chat(client, messages, "Compare laptops under 65000")
    expected_product_id = laptops["suggestions"][0]["product"]["product_id"]

    purchase = chat(client, messages, "Buy the first one")
    assert purchase["next_action"] == "OPEN_VERIFICATION"
    assert len(purchase["suggestions"]) == 1
    assert purchase["suggestions"][0]["product"]["product_id"] == expected_product_id
    assert purchase["suggestions"][0]["product"]["category"] == "laptops"


# TEST 9: a stale product from a previous category never leaks into a new
# category's results (this falls out of NEW_SEARCH always re-querying the
# catalog fresh for the new category rather than filtering old results).
def test_stale_category_product_never_appears_after_a_category_switch(client):
    messages = []
    chat(client, messages, "Find cameras under 70000")
    second = chat(client, messages, "Now show me smartwatches under 30000")

    assert second["intent"]["category"] == "smartwatches"
    assert all(s["product"]["category"] == "smartwatches" for s in second["suggestions"])


# TEST 10 / 11 (image_url / image-search) are covered end-to-end in
# tests/test_product_image_flow.py; conversation-state has no effect on
# that path beyond not corrupting it, checked here for one turn.
def test_recommendation_still_carries_canonical_image_url(client):
    messages = []
    body = chat(client, messages, "Find phones under 50000")
    assert body["suggestions"]
    assert "image_url" in body["suggestions"][0]["product"]


# The acceptance-criteria conversation end-to-end: search -> new search
# -> superlative reference -> purchase reference, each step using only
# the CURRENT candidate set.
def test_full_acceptance_criteria_conversation(client):
    messages = []
    chat(client, messages, "Find a smartphone under 50000 with a good camera")
    laptops = chat(client, messages, "Compare laptops under 65000 with 16GB RAM")
    assert laptops["intent"]["category"] == "laptops"
    assert all(s["product"]["category"] == "laptops" for s in laptops["suggestions"])

    best = chat(client, messages, "Show me the best one")
    assert len(best["suggestions"]) == 1
    assert best["suggestions"][0]["product"]["category"] == "laptops"
    best_product_id = best["suggestions"][0]["product"]["product_id"]

    buy = chat(client, messages, "Buy it")
    assert buy["next_action"] == "OPEN_VERIFICATION"
    assert buy["suggestions"][0]["product"]["product_id"] == best_product_id
    assert buy["suggestions"][0]["product"]["category"] == "laptops"


# A category-shaped word inside a reference-shaped sentence ("Compare
# laptops...") must not be swallowed by the reference classifier just
# because it contains the word "compare" -- regression test for the
# ordering bug found while building this (category change must always be
# checked before treating a message as a reference to old candidates).
def test_compare_keyword_with_a_new_category_is_a_new_search_not_a_comparison(client):
    messages = []
    chat(client, messages, "Find a smartphone under 50000")
    second = chat(client, messages, "Compare laptops under 65000")

    assert second["intent"]["category"] == "laptops"
    assert all(s["product"]["category"] == "laptops" for s in second["suggestions"])
