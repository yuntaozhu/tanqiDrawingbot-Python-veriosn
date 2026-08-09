import re
from typing import Dict, Any, Optional

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
        remove_keywords = ["去掉", "删除", "擦掉", "不要", "抹去", "拿走", "减去", "去"]
        for kw in remove_keywords:
            if kw in text:
                target = text.replace(kw, "").replace("一个", "").replace("只", "").replace("个", "").strip("，。！.!? ")
                return {
                    "type": "remove",
                    "confidence": 0.95 if kw != "去" else 0.8,
                    "raw_target": target or text
                }

        # 2. MODIFY operation keywords detection
        modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
        for kw in modify_keywords:
            if kw in text:
                # E.g. "把小狗的颜色改成白色" -> target: "小狗"
                target = text
                if "把" in text and "改" in text:
                    match = re.search(r"把(.*?)的?颜色?改", text)
                    if match:
                        target = match.group(1).strip()
                return {
                    "type": "modify",
                    "confidence": 0.90,
                    "raw_target": target
                }

        # 3. ADD operation keywords detection
        add_keywords = ["增加", "加一个", "加个", "添一个", "多一个", "再画", "旁边加", "添加", "再增加", "追加", "再加上", "还想画", "还有"]
        for kw in add_keywords:
            if kw in text:
                target = text.split(kw)[-1].replace("一个", "").replace("只", "").replace("个", "").strip("，。！.!? ")
                if "在" in text and "旁边" in text:
                    # E.g. "在小兔子旁边增加一个小狗"
                    match = re.search(r"旁边.*?加.*?(个|只)?(.*)", text)
                    if match:
                        target = match.group(2).strip("，。！.!? ")
                return {
                    "type": "add",
                    "confidence": 0.95,
                    "raw_target": target or text
                }

        # 4. CREATE operation keywords detection
        create_keywords = ["画一个", "画个", "画只", "重新画", "画画", "画个", "绘制"]
        for kw in create_keywords:
            if text.startswith(kw):
                target = text.replace(kw, "").replace("一个", "").replace("只", "").replace("个", "").strip("，。！.!? ")
                return {
                    "type": "create",
                    "confidence": 0.95,
                    "raw_target": target or text
                }

        # 5. Default/Context Inference
        # If there are no clear keywords but it contains drawing verb
        if "画" in text:
            target = text.replace("画", "").strip("，。！.!? ")
            return {
                "type": "create",
                "confidence": 0.85,
                "raw_target": target or text
            }
            
        # Fallback to create with low confidence
        return {
            "type": "create",
            "confidence": 0.50,
            "raw_target": text
        }
