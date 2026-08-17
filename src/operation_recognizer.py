import re
from typing import Dict, Any, Optional


def clean_drawing_target(text: str) -> str:
    """Strip leading measure words without turning 小狗 into 一小狗."""
    t = (text or "").strip("，。！.!?、 ")
    t = re.sub(
        r"^(一个|一只|一条|一张|一幅|一朵|一辆|一架|个|只|条|张|幅)",
        "",
        t,
    )
    return t.strip("，。！.!?、 ") or (text or "").strip()


class OperationRecognizer:
    @staticmethod
    def recognize_operation(user_text: str, last_operation_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Recognize drawing operations (create, add, modify, remove) from child user input.
        Returns a dict: {
            "type": "create" | "add" | "modify" | "remove",
            "confidence": float,
            "raw_target": str
        }
        """
        text = user_text.strip()

        # 1. REMOVE operation keywords detection
        remove_keywords = ["去掉", "删除", "擦掉", "不要", "抹去", "拿走", "减去"]
        for kw in remove_keywords:
            if kw in text:
                target = clean_drawing_target(text.replace(kw, ""))
                return {
                    "type": "remove",
                    "confidence": 0.95,
                    "raw_target": target or text
                }

        # 2. MODIFY operation keywords detection
        modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
        for kw in modify_keywords:
            if kw in text:
                target = text
                if "把" in text and "改" in text:
                    match = re.search(r"把(.*?)的?颜色?改", text)
                    if match:
                        target = match.group(1).strip()
                return {
                    "type": "modify",
                    "confidence": 0.90,
                    "raw_target": clean_drawing_target(target)
                }

        # 3. CREATE: "再画一只小狗" means a new drawing, not add-to-scene.
        create_again_keywords = ["再画一只", "再画一个", "再画个", "再画只", "再画"]
        for kw in create_again_keywords:
            if kw in text:
                target = clean_drawing_target(text.split(kw)[-1])
                return {
                    "type": "create",
                    "confidence": 0.95,
                    "raw_target": target or text
                }

        # 4. ADD operation keywords detection
        add_keywords = [
            "增加", "加一个", "加个", "添一个", "多一个", "旁边加", "添加",
            "再增加", "追加", "再加上", "加上", "还想画", "还有"
        ]
        for kw in add_keywords:
            if kw in text:
                target = clean_drawing_target(text.split(kw)[-1])
                if "在" in text and "旁边" in text:
                    match = re.search(r"旁边.*?加.*?(个|只)?(.*)", text)
                    if match:
                        target = clean_drawing_target(match.group(2))
                return {
                    "type": "add",
                    "confidence": 0.95,
                    "raw_target": target or text
                }

        # 5. CREATE operation keywords detection
        create_keywords = ["画一个", "画一只", "画个", "画只", "重新画", "画画", "绘制"]
        for kw in create_keywords:
            if text.startswith(kw) or kw in text:
                target = clean_drawing_target(text.split(kw)[-1] if kw in text else text.replace(kw, ""))
                return {
                    "type": "create",
                    "confidence": 0.95,
                    "raw_target": target or text
                }

        # 6. Default/Context Inference
        if "画" in text:
            target = clean_drawing_target(text.replace("画", ""))
            return {
                "type": "create",
                "confidence": 0.85,
                "raw_target": target or text
            }

        return {
            "type": "create",
            "confidence": 0.50,
            "raw_target": text
        }
