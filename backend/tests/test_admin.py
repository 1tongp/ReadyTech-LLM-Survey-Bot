HDR = {"Admin-API-Key": "test-key"}

def test_create_survey_questions_and_guidelines(client):
    # create survey with 2 questions
    r = client.post("/admin/surveys", json={
        "title": "Admin Test",
        "description": "desc",
        "questions": [
            {"text":"Q1 must say good", "order_index":0, "type":"text"},
            {"text":"Q2 free",          "order_index":1, "type":"text"},
        ]
    }, headers=HDR)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # get survey detail, should have 2 questions
    d = client.get(f"/admin/surveys/{sid}/detail", headers=HDR).json()
    assert d["survey"]["title"] == "Admin Test"
    assert len(d["questions"]) == 2
    q1_id = d["questions"][0]["id"]
    q2_id = d["questions"][1]["id"]

    # set guideline for Q1
    r2 = client.put(f"/admin/questions/{q1_id}/guideline",
                    json={"content":"must say good"},
                    headers=HDR)
    assert r2.status_code == 200

    # get survey detail again, check guidelines for Q1, and Q2 should be None
    d2 = client.get(f"/admin/surveys/{sid}/detail", headers=HDR).json()
    qs = {q["id"]: q for q in d2["questions"]}
    assert qs[q1_id]["guideline"]["content"] == "must say good"
    assert qs[q2_id]["guideline"] is None

def test_generate_link_once(client):
    # create survey
    sid = client.post("/admin/surveys", json={
        "title":"Link One",
        "questions":[{"text":"Q1","order_index":0}]
    }, headers=HDR).json()["id"]

    # generate link
    r = client.post("/admin/links", json={"survey_id": sid}, headers=HDR)
    assert r.status_code == 200
    token = r.json()["token"]
    assert isinstance(token, str) and "/take/" in r.json()["url"]
