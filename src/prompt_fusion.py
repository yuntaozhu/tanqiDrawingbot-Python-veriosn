"""
Prompt 融合引擎 - 将多轮对话融合成完整的绘图 Prompt
"""
from typing import Dict, Any, List, Optional
from src.logger import setup_logger
from src.operation_recognizer import OperationRecognizer

logger = setup_logger("prompt_fusion")


class PromptFusionEngine:
    """Prompt 融合引擎"""
    
    @classmethod
    def fuse_drawing_prompt(
        cls,
        current_user_text: str,
        operation_type: str,
        previous_prompt: Optional[str] = None,
        scene_elements: Optional[List[str]] = None,
        confidence: float = 0.7
    ) -> Dict[str, Any]:
        """
        融合 Prompt
        
        输入:
        - current_user_text: 当前用户输入
        - operation_type: 操作类型 (create/add/modify/remove)
        - previous_prompt: 前一个有效的完整 Prompt
        - scene_elements: 当前场景的元素列表
        - confidence: 操作识别的置信度
        
        返回结构:
        {
            "operation": "create/add/modify/remove",
            "fused_prompt": "融合后的完整 Prompt",
            "target_element": "目标元素",
            "position": "相对位置(如果是add操作)",
            "new_elements": ["新增的元素"],
            "all_elements_after": ["融合后的所有元素"],
            "instructions": "额外的生成指令"
        }
        """
        
        target = OperationRecognizer.extract_target_element(current_user_text)
        
        if operation_type == "create":
            return cls._fuse_create(current_user_text, target)
        
        elif operation_type == "add":
            position = OperationRecognizer.extract_position(current_user_text)
            return cls._fuse_add(
                current_user_text, target, previous_prompt, 
                scene_elements or [], position
            )
        
        elif operation_type == "modify":
            modification = OperationRecognizer.extract_modification(current_user_text)
            return cls._fuse_modify(
                current_user_text, target, previous_prompt,
                scene_elements or [], modification
            )
        
        elif operation_type == "remove":
            return cls._fuse_remove(
                current_user_text, target, previous_prompt,
                scene_elements or []
            )
        
        # Fallback to create
        return cls._fuse_create(current_user_text, target)
    
    @classmethod
    def _fuse_create(cls, user_text: str, target: Optional[str]) -> Dict[str, Any]:
        """处理 CREATE 操作"""
        fused_prompt = target if target and target not in ["画", "画画", "画图"] else user_text
        
        logger.debug(f"[FUSION] CREATE operation - prompt: {fused_prompt}")
        
        return {
            "operation": "create",
            "fused_prompt": fused_prompt,
            "target_element": target,
            "new_elements": [target] if target else [],
            "all_elements_after": [target] if target else [],
            "instructions": "这是一个全新的画面创建请求,忽略之前的画面信息。"
        }
    
    @classmethod
    def _fuse_add(
        cls,
        user_text: str,
        target: Optional[str],
        previous_prompt: Optional[str],
        scene_elements: List[str],
        position: Optional[str]
    ) -> Dict[str, Any]:
        """处理 ADD 操作"""
        if not target:
            target = "一个新的东西"
        
        if not previous_prompt:
            # 如果没有前一个 Prompt,降级为 CREATE
            logger.warning(f"[FUSION] ADD operation without previous prompt, falling back to CREATE")
            return cls._fuse_create(user_text, target)
        
        # 构建融合 Prompt
        position_desc = cls._position_to_description(position)
        
        fused_prompt = f"""基于已有的画面("{previous_prompt}")的基础上,
在{position_desc}增加一个{target}。
保持整体风格和谐,确保新增元素与现有元素在尺寸、比例和颜色上协调。
保留所有已有的元素: {', '.join(scene_elements) if scene_elements else '现有元素'}。
"""
        
        # 更新场景元素
        new_elements_list = scene_elements.copy() if scene_elements else []
        if target not in new_elements_list:
            new_elements_list.append(target)
        
        logger.debug(f"[FUSION] ADD operation - target: {target}, position: {position}, new elements: {new_elements_list}")
        
        return {
            "operation": "add",
            "fused_prompt": fused_prompt,
            "target_element": target,
            "position": position,
            "new_elements": [target],
            "all_elements_after": new_elements_list,
            "instructions": "这是一个增量修改操作,确保新增元素不会遮挡或改变已有的元素。"
        }
    
    @classmethod
    def _fuse_modify(
        cls,
        user_text: str,
        target: Optional[str],
        previous_prompt: Optional[str],
        scene_elements: List[str],
        modification: Optional[Dict[str, str]]
    ) -> Dict[str, Any]:
        """处理 MODIFY 操作"""
        if not previous_prompt:
            logger.warning(f"[FUSION] MODIFY operation without previous prompt, falling back to CREATE")
            return cls._fuse_create(user_text, target)
        
        if not target:
            target = "画面"
        
        # 构建融合 Prompt
        mod_desc = ""
        if modification:
            attr = modification.get("attribute", "")
            val = modification.get("value", "")
            if attr == "color":
                mod_desc = f"改为{val}色"
            elif attr == "size":
                mod_desc = f"变得{'更大' if val == 'larger' else '更小'}"
            elif attr == "pose":
                mod_desc = f"改为{val}的姿态"
            else:
                mod_desc = f"修改为{val}"
        
        fused_prompt = f"""基于已有的画面("{previous_prompt}")的基础上,
将{target}{mod_desc}。
保持其他所有元素和细节不变。
"""
        
        logger.debug(f"[FUSION] MODIFY operation - target: {target}, modification: {modification}")
        
        return {
            "operation": "modify",
            "fused_prompt": fused_prompt,
            "target_element": target,
            "modification": modification,
            "all_elements_after": scene_elements,
            "instructions": "这是一个属性修改操作,只改变指定元素的指定属性,不改变其他元素。"
        }
    
    @classmethod
    def _fuse_remove(
        cls,
        user_text: str,
        target: Optional[str],
        previous_prompt: Optional[str],
        scene_elements: List[str]
    ) -> Dict[str, Any]:
        """处理 REMOVE 操作"""
        if not previous_prompt:
            logger.warning(f"[FUSION] REMOVE operation without previous prompt, creating new scene")
            return cls._fuse_create(user_text, None)
        
        if not target or target in ["画", "画画", "所有"]:
            # 删除所有元素,等同于 CREATE
            logger.debug(f"[FUSION] REMOVE all elements - equivalent to CREATE")
            return cls._fuse_create(user_text, None)
        
        # 更新场景元素 - 删除目标
        new_elements_list = [e for e in scene_elements if e != target]
        
        # 构建融合 Prompt
        fused_prompt = f"""基于已有的画面("{previous_prompt}")的基础上,
移除{target},保持整体布局和其他元素的协调。
保留的元素: {', '.join(new_elements_list) if new_elements_list else '无'}。
"""
        
        logger.debug(f"[FUSION] REMOVE operation - target: {target}, remaining elements: {new_elements_list}")
        
        return {
            "operation": "remove",
            "fused_prompt": fused_prompt,
            "target_element": target,
            "removed_elements": [target],
            "all_elements_after": new_elements_list,
            "instructions": "这是一个删除操作,移除指定元素但保持画面的整体协调。"
        }
    
    @classmethod
    def _position_to_description(cls, position: Optional[str]) -> str:
        """将位置代码转换为中文描述"""
        position_map = {
            "top": "上面",
            "bottom": "下面",
            "left": "左边",
            "right": "右边",
            "center": "中间",
            "side": "旁边",
            "front": "前面",
            "back": "后面"
        }
        return position_map.get(position, "适当的位置")


class ConversationContextManager:
    """会话上下文管理 - 处理多轮对话的上下文"""
    
    @staticmethod
    def prepare_fusion_inputs(
        current_text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        准备 Prompt 融合的输入
        
        从会话上下文中提取必要的信息,用于 Prompt 融合
        """
        previous_prompt = None
        scene_elements = []
        last_operation_type = None
        
        if context:
            previous_prompt = context.get("last_generated_prompt")
            scene_elements = context.get("scene_elements", [])
            last_operation_type = context.get("last_operation_type")
        
        # 识别当前操作
        operation = OperationRecognizer.recognize_operation(
            current_text,
            last_operation_type=last_operation_type
        )
        
        return {
            "current_text": current_text,
            "operation": operation,
            "previous_prompt": previous_prompt,
            "scene_elements": scene_elements,
            "last_operation_type": last_operation_type
        }
    
    @staticmethod
    def update_context_after_fusion(
        context: Dict[str, Any],
        fusion_result: Dict[str, Any],
        image_url: Optional[str] = None,
        bitmap_hex: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        融合后更新会话上下文
        """
        updated_context = context.copy() if context else {}
        
        # 更新最后生成的 Prompt
        updated_context["last_generated_prompt"] = fusion_result.get("fused_prompt")
        
        # 更新场景元素
        updated_context["scene_elements"] = fusion_result.get("all_elements_after", [])
        
        # 更新最后操作类型
        updated_context["last_operation_type"] = fusion_result.get("operation")
        
        # 更新当前图片信息
        if image_url:
            updated_context["current_image_url"] = image_url
        if bitmap_hex:
            updated_context["current_image_bitmap_hex"] = bitmap_hex
        
        return updated_context

