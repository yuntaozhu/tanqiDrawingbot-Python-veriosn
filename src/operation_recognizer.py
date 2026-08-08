"""
操作识别引擎 - 识别用户请求的操作类型(create/add/modify/remove)
"""
from typing import Dict, Any, Optional, List
import re
from src.logger import setup_logger

logger = setup_logger("operation_recognizer")


class OperationRecognizer:
    """操作类型识别引擎"""
    
    # 关键词定义
    CREATE_KEYWORDS = [
        "从头画", "重新画", "画一个新的", "我想画", "帮我画",
        "可以画", "画一幅", "画一画", "想要画", "能不能画",
        "给我画", "为我画", "画个"
    ]
    
    ADD_KEYWORDS = [
        "加上", "增加", "再加", "旁边加", "再画", "还要画",
        "在...旁边", "在...左边", "在...右边", "在...上面", "在...下面",
        "加一个", "加一只", "再加一个", "还要加", "还要画",
        "左边加", "右边加", "上面加", "下面加"
    ]
    
    MODIFY_KEYWORDS = [
        "改成", "换成", "把...改成", "把...变成", "变一下颜色",
        "大一点", "小一点", "更...", "比较...", "有点太...",
        "变一下", "改改", "调整", "修改", "变色"
    ]
    
    REMOVE_KEYWORDS = [
        "删除", "去掉", "移除", "别要", "不要", "去掉",
        "消除", "清除", "删掉", "没有", "不用"
    ]
    
    POSITION_KEYWORDS = {
        "上面": "top",
        "下面": "bottom",
        "左边": "left",
        "右边": "right",
        "中间": "center",
        "旁边": "side",
        "前面": "front",
        "后面": "back",
        "上方": "top",
        "下方": "bottom",
        "左方": "left",
        "右方": "right"
    }
    
    @classmethod
    def recognize_operation(cls, user_text: str, last_operation_type: Optional[str] = None) -> Dict[str, Any]:
        """
        识别用户请求的操作类型
        
        返回结构:
        {
            "type": "create/add/modify/remove",
            "confidence": 0.0-1.0,
            "raw_target": "用户输入中的目标部分",
            "position": "相对位置(如果是add操作)",
            "reasoning": "识别推理"
        }
        """
        text_lower = user_text.lower()
        
        # 第一阶段: 检查 REMOVE 关键词(优先级最高)
        if cls._match_keywords(text_lower, cls.REMOVE_KEYWORDS):
            logger.debug(f"[RECOGNIZER] Detected REMOVE operation from: {user_text}")
            return {
                "type": "remove",
                "confidence": 0.85,
                "raw_target": user_text,
                "reasoning": "Matched REMOVE keywords"
            }
        
        # 第二阶段: 检查 CREATE 关键词(重新、从头、新的等)
        if any(kw in text_lower for kw in ["重新", "从头", "新的"]):
            logger.debug(f"[RECOGNIZER] Detected CREATE operation (reset) from: {user_text}")
            return {
                "type": "create",
                "confidence": 0.9,
                "raw_target": user_text,
                "reasoning": "Matched CREATE reset keywords"
            }
        
        # 第三阶段: 检查 ADD 关键词(加、增加、旁边等)
        if cls._match_keywords(text_lower, cls.ADD_KEYWORDS):
            position = cls.extract_position(user_text)
            confidence = 0.85 if position else 0.75
            logger.debug(f"[RECOGNIZER] Detected ADD operation from: {user_text}, position: {position}")
            return {
                "type": "add",
                "confidence": confidence,
                "raw_target": user_text,
                "position": position,
                "reasoning": "Matched ADD keywords"
            }
        
        # 第四阶段: 检查 MODIFY 关键词(改、换、变色等)
        if cls._match_keywords(text_lower, cls.MODIFY_KEYWORDS):
            logger.debug(f"[RECOGNIZER] Detected MODIFY operation from: {user_text}")
            return {
                "type": "modify",
                "confidence": 0.8,
                "raw_target": user_text,
                "reasoning": "Matched MODIFY keywords"
            }
        
        # 第五阶段: 上下文增强 - 如果前面已经有画面,则倾向 ADD
        if last_operation_type and last_operation_type in ["create", "add"]:
            # 检查是否有对前一个操作的否定
            if any(neg in text_lower for neg in ["不对", "不行", "重新"]):
                logger.debug(f"[RECOGNIZER] Context suggests CREATE (negation of previous)")
                return {
                    "type": "create",
                    "confidence": 0.7,
                    "raw_target": user_text,
                    "reasoning": "Context negation suggests CREATE"
                }
            
            # 如果没有明确的操作关键词,但前面有画面,倾向 ADD
            logger.debug(f"[RECOGNIZER] Context suggests ADD (continuing previous scene)")
            return {
                "type": "add",
                "confidence": 0.6,
                "raw_target": user_text,
                "position": cls.extract_position(user_text),
                "reasoning": "Context suggests ADD (no explicit keywords)"
            }
        
        # 默认: CREATE(最保险的默认行为)
        logger.debug(f"[RECOGNIZER] No specific keywords matched, defaulting to CREATE")
        return {
            "type": "create",
            "confidence": 0.5,
            "raw_target": user_text,
            "reasoning": "Default fallback to CREATE"
        }
    
    @classmethod
    def _match_keywords(cls, text: str, keywords: List[str]) -> bool:
        """检查文本是否包含关键词列表中的任意一个"""
        return any(kw in text for kw in keywords)
    
    @classmethod
    def extract_position(cls, user_text: str) -> Optional[str]:
        """从用户文本中提取相对位置信息"""
        text_lower = user_text.lower()
        
        # 检查每个位置关键词
        for pos_keyword, pos_value in cls.POSITION_KEYWORDS.items():
            if pos_keyword in text_lower:
                # 检查是否在"在"、"靠"等介词后面
                pattern = f"(在|靠|朝|向)?{re.escape(pos_keyword)}"
                if re.search(pattern, text_lower):
                    logger.debug(f"[RECOGNIZER] Extracted position: {pos_value} from: {user_text}")
                    return pos_value
        
        # 检查"一起"、"互相"等并列词 -> 推断为 side/center
        if any(kw in text_lower for kw in ["一起", "互相"]):
            return "side"
        
        return None
    
    @classmethod
    def extract_target_element(cls, user_text: str, scene_elements: List[str] = None) -> Optional[str]:
        """
        从用户文本中提取目标元素(对象名词)
        
        策略:
        1. 查找常见动物/物体名词
        2. 从场景元素中查找相关词
        3. 使用简单的启发式规则
        """
        text = user_text.strip()
        
        # 常见的对象列表
        common_objects = [
            "小狗", "小猫", "小兔", "小马", "小鹿", "小羊", "小牛",
            "小鸡", "小鸭", "小鹅", "小鸟", "老鹰", "蝴蝶", "蜜蜂",
            "花", "树", "草", "云", "太阳", "月亮", "星星", "彩虹",
            "房子", "汽车", "飞机", "火车", "船", "自行车",
            "苹果", "香蕉", "橙子", "西瓜", "葡萄",
            "狗", "猫", "兔", "马", "鹿", "羊", "牛", "鸡", "鸭", "鹅"
        ]
        
        # 移除前缀
        prefixes = [
            "我想画一个", "我想画一只", "帮我画一个", "帮我画一只",
            "画一个", "画一只", "画个", "画只",
            "加一个", "加一只", "加个", "加只",
            "在...旁边", "在...左边", "在...右边", "增加", "加上",
            "改成", "换成", "把", "变成"
        ]
        
        processed_text = text
        for prefix in prefixes:
            # 简单的前缀移除(不需要精确匹配"...")
            if prefix.replace("...", "") in processed_text:
                processed_text = processed_text.replace(prefix.replace("...", ""), "", 1)
        
        processed_text = processed_text.strip("。，！？.!? ")
        
        # 后缀清理
        suffixes = ["吧", "呀", "呗", "呢", "吗", "哈", "啦", "了", "的", "不"]
        for suffix in suffixes:
            if processed_text.endswith(suffix):
                processed_text = processed_text[:-len(suffix)]
        
        processed_text = processed_text.strip()
        
        # 如果移除前缀后的文本包含常见对象,使用该对象
        for obj in common_objects:
            if obj in processed_text:
                logger.debug(f"[RECOGNIZER] Extracted target element: {obj} from: {user_text}")
                return obj
        
        # 如果无法识别,返回整个处理后的文本
        if processed_text and processed_text not in ["画", "画画", "画图"]:
            logger.debug(f"[RECOGNIZER] Extracted target element (generic): {processed_text} from: {user_text}")
            return processed_text
        
        return None
    
    @classmethod
    def extract_modification(cls, user_text: str) -> Optional[Dict[str, str]]:
        """
        从 MODIFY 操作的文本中提取修改属性
        
        返回: {"attribute": "color/size/pose/...", "value": "具体值"}
        """
        text_lower = user_text.lower()
        
        # 颜色修改
        colors = ["红", "绿", "蓝", "黄", "紫", "粉", "橙", "黑", "白", "灰", "金", "银"]
        for color in colors:
            if f"改成{color}" in text_lower or f"变{color}" in text_lower or f"换{color}" in text_lower:
                return {"attribute": "color", "value": color}
        
        # 大小修改
        if "大一点" in text_lower or "更大" in text_lower:
            return {"attribute": "size", "value": "larger"}
        if "小一点" in text_lower or "更小" in text_lower:
            return {"attribute": "size", "value": "smaller"}
        
        # 姿态/表情修改
        poses = ["跑", "跳", "飞", "睡", "坐", "站", "趴"]
        for pose in poses:
            if f"改成{pose}" in text_lower or f"变{pose}" in text_lower:
                return {"attribute": "pose", "value": pose}
        
        return None

