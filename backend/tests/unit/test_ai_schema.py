from app.domain.ai_schema import normalize_provider_payload


def test_sparse_observations_do_not_invent_off_frame_content() -> None:
    payload = {
        "scene_observations": {
            "space_type": "现代住宅客厅",
            "style": "现代极简奶油风",
            "floor": "浅木色人字拼地板",
        },
        "positive_prompt": "现代住宅客厅，浅木色人字拼地板",
    }

    result = normalize_provider_payload(payload)

    assert result.scene_observations.space_type == "现代住宅客厅"
    assert result.scene_observations.layout == ""
    assert result.scene_observations.window == ""
    assert result.scene_observations.dining_kitchen == ""
    assert result.scene_observations.architecture == []
    assert "餐厨" not in result.positive_prompt


def test_invalid_sibling_uses_neutral_value_but_preserves_valid_fields() -> None:
    payload = {
        "sofa_product": {"color": "米白色", "immutable_features": "错误类型"},
        "scene_observations": {"style": "现代风", "architecture": {"bad": True}},
        "positive_prompt": "米白色沙发，现代风客厅",
        "negative_prompt": "镜像，强行转正",
    }

    result = normalize_provider_payload(payload)

    assert result.sofa_product.color == "米白色"
    assert result.sofa_product.immutable_features == []
    assert result.scene_observations.style == "现代风"
    assert result.scene_observations.architecture == []
    assert result.negative_prompt == "镜像，强行转正"


def test_wrapped_fenced_segment_payload_is_normalized() -> None:
    content = [
        {"type": "text", "text": "说明文字\n```json\n"},
        {
            "type": "text",
            "text": '{"result":{"positive_prompt":"可见客厅","negative_prompt":"镜像"}}',
        },
        {"type": "text", "text": "\n```"},
    ]

    result = normalize_provider_payload(content)

    assert result.positive_prompt == "可见客厅"
    assert result.negative_prompt == "镜像"
    assert result.scene_observations.dining_kitchen == ""


def test_provider_review_checklist_and_view_aliases_are_normalized() -> None:
    result = normalize_provider_payload(
        {
            "sofa_view": {
                "view_angle": "正面偏右的高位三分之四视角",
                "visible_sides": ["正面", "右侧近端", "左侧远端"],
                "orientation": {
                    "near_end": "画面右侧末端",
                    "far_end": "画面左侧末端",
                },
            },
            "positive_prompt": "非空正向提示词",
            "negative_prompt": "不要镜像",
            "review": {
                "six_modules_present": True,
                "product_style_preserved": True,
                "orientation_preserved": True,
                "near_far_preserved": True,
                "uncertain_fields": [],
            },
        }
    )

    assert result.sofa_view.view_type == "正面偏右的高位三分之四视角"
    assert result.sofa_view.near_end == "画面右侧末端"
    assert result.sofa_view.far_end == "画面左侧末端"
    assert result.sofa_view.evidence == ["正面", "右侧近端", "左侧远端"]
    assert result.review.required is False
    assert result.review.reasons == []


def test_provider_text_review_checks_and_proximal_aliases_are_approved() -> None:
    result = normalize_provider_payload(
        {
            "sofa_view": {
                "viewpoint": "略高于沙发的正面斜视角",
                "orientation": {
                    "proximal_end": "画面右侧端部",
                    "distal_end": "画面左侧端部",
                },
            },
            "positive_prompt": "完整提示词",
            "review": {
                "module_check": "模块均已明确保留",
                "style_check": "款式已保留",
                "direction_check": "未镜像",
                "proximal_distal_check": "右侧近端，左侧远端",
                "uncertain_fields": "",
            },
        }
    )

    assert result.sofa_view.view_type == "略高于沙发的正面斜视角"
    assert result.sofa_view.near_end == "画面右侧端部"
    assert result.sofa_view.far_end == "画面左侧端部"
    assert result.review.required is False
    assert result.review.reasons == []
