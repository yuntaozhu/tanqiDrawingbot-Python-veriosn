import datetime
from typing import List, Dict, Any, Optional
from src.operation_recognizer import OperationRecognizer

class PromptFusionEngine:
    @staticmethod
    def fuse_drawing_prompt(
        current_user_text: str,
        operation_type: str,
        previous_prompt: Optional[str] = None,
        scene_elements: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fuse previous prompt and elements with the current user request based on the operation type.
        """
        scene_elements = scene_elements or []
        
        # Recognize operation to extract targets
        op_info = OperationRecognizer.recognize_operation(current_user_text)
        target = op_info.get("raw_target") or current_user_text
        
        all_elements_after = list(scene_elements)
        fused_prompt = current_user_text
        
        if operation_type == "create":
            # Start fresh
            fused_prompt = current_user_text
            all_elements_after = [target] if target else [current_user_text]
            
        elif operation_type == "add":
            # Add new element to history
            if target and target not in all_elements_after:
                all_elements_after.append(target)
            
            elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
            fused_prompt = f"基于已有包含 {elements_str} 的画面，在合适的位置增加一个 {target}。整个画面保持黑白卡通画风。"
            
        elif operation_type == "modify":
            # Modify existing element attributes (elements list remains identical or updated)
            elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
            fused_prompt = f"基于包含 {elements_str} 的已有画面，保持整体结构和其他角色不变，进行以下修改：{current_user_text}。"
            
        elif operation_type == "remove":
            # Remove target element from list
            if target in all_elements_after:
                try:
                    all_elements_after.remove(target)
                except ValueError:
                    pass
            else:
                # Try partial matching to remove element
                for elem in list(all_elements_after):
                    if target in elem or elem in target:
                        try:
                            all_elements_after.remove(elem)
                        except ValueError:
                            pass
                            
            elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
            fused_prompt = f"基于包含 {elements_str} 的已有画面，擦除/移除其中所有的 {target}，保留其他元素并使其在画面中完美和谐。"
            
        # Guarantee we don't have empty elements list
        if not all_elements_after:
            all_elements_after = [target] if target else [current_user_text]

        return {
            "operation": operation_type,
            "fused_prompt": fused_prompt,
            "target_element": target,
            "all_elements_after": all_elements_after
        }

class ConversationContextManager:
    @staticmethod
    def prepare_fusion_inputs(user_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare the inputs needed for prompt fusion from the current user text and loaded context.
        """
        last_op = context.get("last_operation_type")
        operation = OperationRecognizer.recognize_operation(user_text, last_op)
        
        return {
            "operation": operation,
            "previous_prompt": context.get("last_generated_prompt"),
            "scene_elements": context.get("scene_elements", [])
        }

    @staticmethod
    def update_context_after_fusion(
        context: Dict[str, Any],
        fusion_result: Dict[str, Any],
        image_url: Optional[str] = None,
        bitmap_hex: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update the context dictionary with fusion results and generated image metadata.
        """
        context["last_generated_prompt"] = fusion_result.get("fused_prompt")
        context["last_operation_type"] = fusion_result.get("operation")
        context["scene_elements"] = fusion_result.get("all_elements_after", [])
        
        if image_url:
            context["current_image_url"] = image_url
        if bitmap_hex:
            context["current_image_bitmap_hex"] = bitmap_hex
            
        return context
