# backend/tests/test_public.py
HDR = {"Admin-API-Key": "test-key"}

def _make_survey_with_link_and_gl(client):
    sid = client.post("/admin/surveys", json={
        "title":"Public Flow",
        "questions":[{"text":"Q1 must say good","order_index":0}]
    }, headers=HDR).json()["id"]
    q1 = client.get(f"/admin/surveys/{sid}/detail", headers=HDR).json()["questions"][0]["id"]
    client.put(f"/admin/questions/{q1}/guideline", json={"content":"must say good"}, headers=HDR)
    token = client.post("/admin/links", json={"survey_id": sid}, headers=HDR).json()["token"]
    return sid, q1, token

def test_public_flow_answer_crud(client):
    sid, q1, token = _make_survey_with_link_and_gl(client)

    # load survey via public token
    j = client.get(f"/public/surveys/{token}").json()
    assert j["survey"]["id"] == sid
    assert len(j["questions"]) == 1

    # create respondent
    rid = client.post("/public/respondents", json={"link_token": token}).json()["respondent_id"]
    assert isinstance(rid, int)

    # answer the question（without "good" answer will give a low mark & low_quality=True）
    a = client.post("/public/answers", json={
        "respondent_id": rid, "question_id": q1, "answer_text":"meh"
    }).json()
    assert a["score"] == 1.0 and a["low_quality"] is True

    # update the answer to contain "good" will get a high mark & low_quality=False
    a2 = client.put(f"/public/answers/{a['id']}", json={
        "answer_text":"very good content"
    }).json()
    assert a2["score"] == 4.5 and a2["low_quality"] is False

    # Flag/Unflag
    a3 = client.put(f"/public/answers/{a['id']}", json={"flagged": True}).json()
    assert a3["flagged"] is True
    a4 = client.put(f"/public/answers/{a['id']}", json={"flagged": False}).json()
    assert a4["flagged"] is False

    # List answers
    lst = client.get(f"/public/respondents/{rid}/answers").json()
    assert len(lst) == 1 and lst[0]["id"] == a["id"]

    # Delete answer
    assert client.delete(f"/public/answers/{a['id']}").status_code == 200
    lst2 = client.get(f"/public/respondents/{rid}/answers").json()
    assert lst2 == []

def test_invalid_public_token(client):
    # invalid token
    r = client.get("/public/surveys/THIS_IS_INVALID")
    assert r.status_code in (400, 404, 422)
