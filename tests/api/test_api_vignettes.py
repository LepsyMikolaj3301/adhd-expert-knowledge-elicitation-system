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
        ({"question_ids": ["Q1", "Q1"]}, "duplicate_question_id"),
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
