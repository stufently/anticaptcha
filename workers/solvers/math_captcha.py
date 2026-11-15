"""Math CAPTCHA solver"""
import asyncio
import re
from typing import Dict, Any
from .base import BaseSolver


class MathCaptchaSolver(BaseSolver):
    """
    Math CAPTCHA solver - arithmetic problems
    
    Math CAPTCHA uses:
    - Simple arithmetic (addition, subtraction, multiplication)
    - Text or image-based problems
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Math CAPTCHA"""
        page_url = input_data.get('page_url')
        
        if not page_url:
            return {'success': False, 'error': 'Missing page_url'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for math problem
                await page.wait_for_selector('.math-captcha, [class*="math"]', timeout=10000)
                
                # Get problem text
                problem_elem = await page.query_selector('.math-problem, .captcha-text')
                if not problem_elem:
                    return {'success': False, 'error': 'Math problem not found'}
                
                problem = await problem_elem.text_content()
                
                # Parse and solve math problem
                answer = self._solve_math(problem)
                
                if answer is None:
                    # Try using Vision LLM for image-based math
                    from workers.classifiers.vision_llm import VisionLLMClassifier
                    classifier = VisionLLMClassifier()
                    
                    screenshot = await page.screenshot()
                    result = await classifier.classify_image(
                        screenshot,
                        "Solve this math problem. Return only the numeric answer."
                    )
                    
                    try:
                        answer = int(result.strip())
                    except Exception:
                        return {'success': False, 'error': 'Could not solve math problem'}
                
                # Enter answer
                input_field = await page.query_selector('input[name="captcha"], input[type="number"]')
                if input_field:
                    await input_field.fill(str(answer))
                    
                    # Submit
                    submit = await page.query_selector('button[type="submit"], .captcha-submit')
                    if submit:
                        await submit.click()
                        await asyncio.sleep(2)
                    
                    return {'success': True, 'answer': answer}
                else:
                    return {'success': False, 'error': 'Input field not found'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _solve_math(self, problem: str) -> int:
        """Solve simple math problem"""
        # Remove whitespace
        problem = problem.strip()
        
        # Try to parse simple arithmetic
        # Examples: "5 + 3", "10 - 4", "6 * 2", "12 / 3"
        match = re.match(r'(\d+)\s*([+\-*/])\s*(\d+)', problem)
        if match:
            num1 = int(match.group(1))
            op = match.group(2)
            num2 = int(match.group(3))
            
            if op == '+':
                return num1 + num2
            elif op == '-':
                return num1 - num2
            elif op == '*':
                return num1 * num2
            elif op == '/':
                return num1 // num2
        
        # Try word problems
        # Examples: "five plus three", "ten minus four"
        word_to_num = {
            'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
            'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
            'ten': 10
        }
        
        problem_lower = problem.lower()
        for word, num in word_to_num.items():
            problem_lower = problem_lower.replace(word, str(num))
        
        # Try again with numbers
        match = re.match(r'(\d+)\s*(plus|minus|times|divided by)\s*(\d+)', problem_lower)
        if match:
            num1 = int(match.group(1))
            op = match.group(2)
            num2 = int(match.group(3))
            
            if op == 'plus':
                return num1 + num2
            elif op == 'minus':
                return num1 - num2
            elif op == 'times':
                return num1 * num2
            elif op == 'divided by':
                return num1 // num2
        
        return None
