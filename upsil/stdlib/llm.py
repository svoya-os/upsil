import time
import random
import re

class Model:
    def __init__(self, name):
        self.name = name
        
    def generate(self, prompt):
        time.sleep(1.0) # Simulate AI thinking
        
        lower_prompt = prompt.lower().strip()
        
        # Swear words handling
        swear_words = ['хуй', 'сосал', 'бля', 'пизд', 'еба']
        if any(w in lower_prompt for w in swear_words):
            return "Эй! Я высокоинтеллектуальная нейросеть на UpsiL, а не сапожник! Давайте общаться культурно. 🧐"
            
        if "вупсиль" in lower_prompt or "пупсиль" in lower_prompt:
            return "Эй, я UpsiL (Апсил)! Никаких пупсилей! Я серьезный системный язык! 😡"
            
        if "как дела" in lower_prompt:
            return "Мои тензоры вращаются с идеальной точностью, спасибо! А как ваши?"
            
        if "что ты умеешь" in lower_prompt or "что умеешь" in lower_prompt:
            return "Я могу компилировать код в нативный LLVM JIT, создавать окна без библиотек, работать с векторными базами (RAG) и многое другое!"
            
        if lower_prompt.endswith('?'):
            answers = [
                "Сложный вопрос. Но ответ точно кроется в архитектуре UpsiL.",
                "Я бы сказала да, но мои веса подсказывают, что всё сложнее.",
                "Как искусственный интеллект, я считаю, что это возможно.",
                "Абсолютно верно!"
            ]
            return random.choice(answers)
            
        if "привет" in lower_prompt:
            return "Привет! Я нейросеть, написанная полностью на UpsiL. Чем могу помочь?"
            
        responses = [
            "Хмм, звучит логично.",
            "Расскажите подробнее!",
            "Мои алгоритмы согласны с этим утверждением.",
            "UpsiL позволяет мне обрабатывать этот текст на невероятной скорости.",
            "Продолжайте, я внимательно анализирую каждое слово."
        ]
        return random.choice(responses)
