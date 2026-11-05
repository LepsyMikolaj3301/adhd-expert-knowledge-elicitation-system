import pytest
from api_helpers import (
    CUE,
    DESIGN_SECRET,
    VIGNETTE_TEXT,
    admin_api,
    assign,
    expert_api,
    published_version,
    vignette_body,
)


async def test_create_edit_publish_retire():
    admin = await admin_api()
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body("V001"))
    version = vignette["versions"][0]
    assert version["version"] == 1
    assert version["status"] == "draft"
    assert version["word_count"] == len(VIGNETTE_TEXT.split())

    new_text = VIGNETTE_TEXT + " extra"
    edited = await admin.ok("PATCH", f"/vignette-versions/{version['id']}", json={"text": new_text})
    assert edited["text"] == new_text
    assert edited["content_hash"] != version["content_hash"]

    published = await admin.ok("POST", f"/vignette-versions/{version['id']}/publish")
    assert published["status"] == "published"
    assert published["published_at"]
    await admin.fails(
        "PATCH",
        f"/vignette-versions/{version['id']}",
        409,
        "version_not_draft",
        json={"text": VIGNETTE_TEXT},
    )
    await admin.fails(
        "POST", f"/vignette-versions/{version['id']}/publish", 409, "version_not_draft"
    )
    retired = await admin.ok("POST", f"/vignette-versions/{version['id']}/retire")
    assert retired["status"] == "retired"
    await admin.fails(
        "POST", f"/vignette-versions/{version['id']}/retire", 409, "version_not_published"
    )


async def test_new_versions_count_up_and_duplicate_code_is_refused():
    admin = await admin_api()
    body = vignette_body("V001")
    vignette = await admin.ok("POST", "/vignettes", 201, json=body)
    await admin.fails("POST", "/vignettes", 409, "vignette_code_taken", json=body)
    content = {key: value for key, value in body.items() if key != "code"}
    second = await admin.ok("POST", f"/vignettes/{vignette['id']}/versions", 201, json=content)
    assert second["version"] == 2
    listed = await admin.ok("GET", "/vignettes")
    assert [v["version"] for v in listed[0]["versions"]] == [1, 2]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"q4_whatif": None}, "q4_without_whatif"),
        ({"q4_whatif": "   "}, "q4_without_whatif"),
        (
            {
                "design": {
                    "purpose": "x",
                    "is_control": True,
                    "planted_cues": [{"quote": CUE, "trait": "t", "strength": "weak"}],
                }
            },
            "control_with_cues",
        ),
        ({"design": {"purpose": "x", "track": "text_analysis"}}, "track_without_target"),
        (
            {
                "design": {
                    "purpose": "x",
                    "confounders": [{"quote": "not in the text", "alternative_explanation": "y"}],
                }
            },
            "span_not_in_text",
        ),
        ({"variant": {"pair_id": "P1", "arm": "B"}}, "variant_b_without_change"),
    ],
)
async def test_content_rules_have_stable_codes(overrides, code):
    admin = await admin_api()
    await admin.fails("POST", "/vignettes", 422, code, json=vignette_body(**overrides))


ALL_QUESTIONS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]


async def test_every_version_asks_all_six_questions():
    admin = await admin_api()
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    version = vignette["versions"][0]
    assert version["question_ids"] == ALL_QUESTIONS
    edited = await admin.ok(
        "PATCH", f"/vignette-versions/{version['id']}", json={"q4_whatif": "the writer slept well"}
    )
    assert edited["question_ids"] == ALL_QUESTIONS
    second = await admin.ok(
        "POST",
        f"/vignettes/{vignette['id']}/versions",
        201,
        json={k: v for k, v in vignette_body().items() if k != "code"},
    )
    assert second["question_ids"] == ALL_QUESTIONS


async def test_the_admin_cannot_choose_the_questions():
    admin = await admin_api()
    body = vignette_body(question_ids=["Q1", "Q2", "Q3"])
    response = await admin.request("POST", "/vignettes", json=body)
    assert response.status_code == 422
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    version_id = vignette["versions"][0]["id"]
    response = await admin.request(
        "PATCH", f"/vignette-versions/{version_id}", json={"question_ids": ["Q1"]}
    )
    assert response.status_code == 422


async def test_a_missing_whatif_is_refused_even_for_a_draft():
    admin = await admin_api()
    body = vignette_body()
    del body["q4_whatif"]
    await admin.fails("POST", "/vignettes", 422, "q4_without_whatif", json=body)
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    await admin.fails(
        "PATCH",
        f"/vignette-versions/{vignette['versions'][0]['id']}",
        422,
        "q4_without_whatif",
        json={"q4_whatif": "  "},
    )


async def test_an_admin_written_vignette_is_hand_written_by_default():
    admin = await admin_api()
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    assert vignette["versions"][0]["design"]["origin"] == "hand_written"
    llm = await admin.ok(
        "POST",
        "/vignettes",
        201,
        json=vignette_body(design={"purpose": "x", "origin": "llm"}),
    )
    assert llm["versions"][0]["design"]["origin"] == "llm"


@pytest.mark.parametrize(
    ("overrides", "field", "term"),
    [
        ({"text": VIGNETTE_TEXT + " My ADHD makes this hard."}, "text", "ADHD"),
        ({"text": VIGNETTE_TEXT + " An attention-deficit story."}, "text", "attention-deficit"),
        (
            {"text": VIGNETTE_TEXT + " They put me on Attention Deficit pills."},
            "text",
            "Attention Deficit",
        ),
        ({"text": VIGNETTE_TEXT + " I take ritalin daily."}, "text", "ritalin"),
        ({"q4_whatif": "the writer takes methylphenidate"}, "q4_whatif", "methylphenidate"),
        ({"q4_whatif": "the writer has ADHD"}, "q4_whatif", "ADHD"),
    ],
)
async def test_publishing_refuses_words_that_name_the_construct(overrides, field, term):
    admin = await admin_api()
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body(**overrides))
    version_id = vignette["versions"][0]["id"]
    error = await admin.fails(
        "POST", f"/vignette-versions/{version_id}/publish", 422, "construct_word_in_text"
    )
    assert error["details"] == {"field": field, "term": term}
    listed = await admin.ok("GET", "/vignettes")
    assert listed[0]["versions"][0]["status"] == "draft"


async def test_ordinary_words_that_look_like_the_construct_are_fine():
    admin = await admin_api()
    text = VIGNETTE_TEXT + " I add milk. My medication is a vitamin. Hyperfocus on the add-on."
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body(text=text))
    published = await admin.ok(
        "POST", f"/vignette-versions/{vignette['versions'][0]['id']}/publish"
    )
    assert published["status"] == "published"


async def test_patch_is_checked_against_the_merged_content():
    admin = await admin_api()
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    version_id = vignette["versions"][0]["id"]
    # The cue quotes stop matching if the text is replaced.
    await admin.fails(
        "PATCH", f"/vignette-versions/{version_id}", 422, "span_not_in_text", json={"text": "new"}
    )
    # A null for a required field is well-formed for PATCH but not for the version.
    await admin.fails(
        "PATCH", f"/vignette-versions/{version_id}", 422, "validation_error", json={"text": None}
    )


@pytest.mark.parametrize("text", ["short text", " ".join(["word"] * 251)])
async def test_publish_requires_the_word_range(text):
    admin = await admin_api()
    body = vignette_body(text=text, design={"purpose": "x"})
    vignette = await admin.ok("POST", "/vignettes", 201, json=body)
    await admin.fails(
        "POST",
        f"/vignette-versions/{vignette['versions'][0]['id']}/publish",
        422,
        "word_count_out_of_range",
    )


async def test_only_published_versions_can_be_assigned():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body())
    version = vignette["versions"][0]
    await admin.fails(
        "POST",
        f"/vignette-versions/{version['id']}/assignments",
        409,
        "version_not_published",
        json={"expert_ids": [expert.user_id]},
    )
    await admin.ok("POST", f"/vignette-versions/{version['id']}/publish")
    await admin.ok("POST", f"/vignette-versions/{version['id']}/retire")
    await admin.fails(
        "POST",
        f"/vignette-versions/{version['id']}/assignments",
        409,
        "version_not_published",
        json={"expert_ids": [expert.user_id]},
    )


async def test_retiring_keeps_existing_assignments_working():
    admin = await admin_api()
    expert = await expert_api("e@example.com")
    version = await published_version(admin)
    [assignment_id] = await assign(admin, version, expert)
    await admin.ok("POST", f"/vignette-versions/{version['id']}/retire")
    view = await expert.ok("POST", f"/assignments/{assignment_id}/start")
    assert view["state"] == "in_progress"
    assert DESIGN_SECRET not in str(view)
