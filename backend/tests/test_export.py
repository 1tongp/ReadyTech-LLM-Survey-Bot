import io, csv
HDR = {"Admin-API-Key": "test-key"}

def test_export_csv_after_submit(client):
    # create survey + guideline + link
    sid = client.post("/admin/surveys", json={
        "title":"Export Survey",
        "questions":[
            {"text":"Q1 must say good","order_index":0},
            {"text":"Q2 free","order_index":1}
        ],
    }, headers=HDR).json()["id"]

    det = client.get(f"/admin/surveys/{sid}/detail", headers=HDR).json()
    q1 = det["questions"][0]["id"]
    client.put(f"/admin/questions/{q1}/guideline", json={"content":"must say good"}, headers=HDR)

    token = client.post("/admin/links", json={"survey_id": sid}, headers=HDR).json()["token"]
    rid = client.post("/public/respondents", json={"link_token": token}).json()["respondent_id"]

    # answer question 1 with good content
    a = client.post("/public/answers", json={
        "respondent_id": rid, "question_id": q1, "answer_text":"good answer here"
    }).json()
    assert a["score"] >= 4.0

    # submit respondent with at least one answered question
    s = client.post("/public/submit", json={"respondent_id": rid})
    assert s.status_code == 200

    # export CSV
    r = client.get(f"/admin/surveys/{sid}/export.csv", headers=HDR)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type","")

    content = r.content.decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    header = next(reader)
    
    # check columns
    for col in ["respondent_id","status","order_index","question","answer_text","flagged","score","rationale","low_quality"]:
        assert col in header
