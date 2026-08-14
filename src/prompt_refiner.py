"""
LLM Prompt Refiner: 从对话历史自动提炼绘画提示词
"""
import asyncio
import time
from typing import Optional, Dict, List, Any
from src.logger import setup_logger
from src.services import DoubaoAPI, DeepSeekAPI
from src.conversation_crud import ConversationManager

logger = setup_logger("prompt_refiner")


class PromptRefinerEngine:
    """
    根据对话历史自动提炼标准化的绘画提示词
    用于处理"画出来"等模糊命令
    """
    
    SYSTEM_PROMPT = """你是一个绘画提示词专家。请分析以下聊天记录,提取出用户想要绘制的核心画面主题。输出一句30字以内的标准画画描述词,要求包含主体、细节、颜色和儿童绘本风格。只需返回提示词文本,不要解释或其他内容。"""
    
    @staticmethod
    def refine_from_conversation_history(
        device_token: str,
        last_n: int = 10
    ) -> Optional[str]:
        """
        从对话历史提炼绘画提示词
        
        Args:
            device_token: 设备令牌
            last_n: 回溯的最近对话轮数
            
        Returns:
            refined_prompt: 提炼后的绘画提示词 (30字以内)
        """
        # 1. 加载对话历史
        context = ConversationManager.get_conversation_context(device_token)
        if not context:
            logger.warning(f"[REFINER] No conversation context found for {device_token}")
            return None
            
        message_history = context.get("message_history", []) or []
        if not message_history:
            logger.warning(f"[REFINER] Empty message history for {device_token}")
            return None
            
        # 2. 提取最近N轮对话
        recent_messages = message_history[-last_n:]
        
        # 构建对话文本
        chat_text = ""
        for msg in recent_messages:
            user_text = (msg or {}).get("user_text", "")
            ai_response = (msg or {}).get("ai_response", "")
            
            if user_text:
                chat_text += f"小朋友说: {user_text}\n"
            if ai_response:
                chat_text += f"小探宝说: {ai_response}\n"
                
        if not chat_text.strip():
            logger.warning(f"[REFINER] Cannot extract chat text from history for {device_token}")
            return None
            
        logger.debug(f"[REFINER] Chat context ({len(recent_messages)} messages):\n{chat_text[:200]}...")
        
        # 3. 调用LLM进行提炼
        refined_prompt = None
        
        doubao = DoubaoAPI.get_instance()
        deepseek = DeepSeekAPI.get_instance()
        
        # 尝试豆包
        if doubao.client:
            try:
                logger.debug(f"[REFINER] Calling Doubao to refine prompt...")
                response = doubao.client.chat.completions.create(
                    model=doubao.audio_model,
                    messages=[
                        {"role": "system", "content": PromptRefinerEngine.SYSTEM_PROMPT},
                        {"role": "user", "content": f"请根据以下聊天记录提炼绘画提示词:\n\n{chat_text}"}
                    ],
                    timeout=15
                )
                if response and response.choices:
                    refined_prompt = response.choices[0].message.content.strip()
                    logger.info(f"[REFINER] Doubao refined prompt: {refined_prompt}")
                    return refined_prompt
            except Exception as e:
                logger.warning(f"[REFINER] Doubao refine failed: {e}, falling back to DeepSeek")
        
        # 降级到DeepSeek
        if deepseek:
            try:
                logger.debug(f"[REFINER] Calling DeepSeek to refine prompt...")
                result = deepseek.generate_text(
                    prompt=f"请根据以下聊天记录提炼绘画提示词:\n\n{chat_text}",
                    system_instruction=PromptRefinerEngine.SYSTEM_PROMPT,
                    timeout=15
                )
                if result and result.get("text"):
                    refined_prompt = result["text"].strip()
                    logger.info(f"[REFINER] DeepSeek refined prompt: {refined_prompt}")
                    return refined_prompt
            except Exception as e:
                logger.error(f"[REFINER] DeepSeek refine also failed: {e}")
        
        # 4. 降级处理: 如果LLM失败,使用启发式方法
        if not refined_prompt:
            logger.warning(f"[REFINER] LLM refine failed, using heuristic extraction...")
            refined_prompt = PromptRefinerEngine._heuristic_extract(chat_text)
            
        logger.info(f"[REFINER] Final refined prompt: {refined_prompt}")
        return refined_prompt
    
    @staticmethod
    def _heuristic_extract(chat_text: str) -> str:
        """
        启发式提炼: 当LLM失败时使用
        """
        lines = chat_text.split("\n")
        
        # 找所有用户的描述 (不包含"画"关键词)
        descriptions = []
        for line in lines:
            if "小朋友说:" in line:
                text = line.replace("小朋友说:", "").strip()
                if text and "画" not in text:
                    descriptions.append(text)
        
        if descriptions:
            # 取最后一条描述
            result = descriptions[-1]
            if len(result) > 30:
                result = result[:30]
            return result
        
        # 最后的降级: 返回通用提示
        return "可爱的小朋友和小动物，儿童绘本风格"

