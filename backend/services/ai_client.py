from enum import Enum
from typing import Optional

from openai import OpenAI
import google.genai as genai
from groq import Groq
from core.settings import get_api_key, settings
from core.logging_config import logger
from core.messages import Messages
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

class AIProvider(str, Enum):
    """Enumeration of supported AI providers.
    
    This enum defines the different AI service providers that can be used
    for code evaluation and chat functionality.
    
    Attributes:
        OPENAI: OpenAI API provider
        GEMINI: Google Gemini API provider  
        GROQ: Groq API provider
    """
    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"


class AIClient:
    """AI client for interacting with different AI service providers.
    
    This class provides a unified interface for connecting to and communicating
    with various AI providers (OpenAI, Gemini, Groq) for code evaluation tasks.
    It handles authentication, client initialization, and chat interactions.
    
    Attributes:
        provider (AIProvider): The AI provider to use for requests
        model (Optional[str]): The specific model to use from the provider
        api_key (Optional[str]): API key for authentication (optional if configured globally)
        client: The initialized client instance for the selected provider
    """
    
    def __init__(
        self,
        provider: AIProvider = AIProvider.GEMINI,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Initialize the AI client with the specified provider and configuration.
        
        Args:
            provider (AIProvider): The AI provider to use. Defaults to GEMINI.
            model (Optional[str]): The specific model to use from the provider.
                If None, the default model for the provider will be used.
            api_key (Optional[str]): API key for authentication. If None, 
                the key will be retrieved from the global configuration.
                
        Raises:
            ValueError: If an unsupported AI provider is specified.
            
        Example:
            >>> client = AIClient(provider=AIProvider.OPENAI, model="gpt-4")
            >>> client = AIClient(provider=AIProvider.GEMINI, api_key="your-api-key")
        """
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.client = self._get_client()
        if api_key is None:
            logger.debug(f"Provider: {provider}, Model: {model}, API Key: {api_key}")
        else:
            logger.debug(f"Provider: {provider}, Model: {model}, API Key: {api_key[:5]}")
        logger.debug(f"Client: {self.client}")

    def _get_client(self):
        """Initialize and return the appropriate client based on the provider.
        
        Returns:
            The initialized client instance for the selected AI provider.
            
        Raises:
            ValueError: If the provider is not supported.
            
        Note:
            This is an internal method that handles the provider-specific
            client initialization logic.
        """
        if self.provider == AIProvider.OPENAI:
            try:
                api_key = self.api_key or get_api_key(AIProvider.OPENAI)
                return OpenAI(api_key=api_key)
            except Exception as e:
                raise ValueError(Messages.AIProvider.INITIALIZATION_FAILED.format(
                    provider=self.provider, 
                    error=str(e)
                ))

        if self.provider == AIProvider.GEMINI:
            try:
                # BYOK Gemini keeps using the Developer API key path.
                if self.api_key:
                    logger.info("AIClient Gemini path: Developer API (BYOK)")
                    return genai.Client(api_key=self.api_key)

                # Server default Gemini path can use Vertex AI with ADC.
                if settings.VERTEX_ENABLED:
                    logger.info("AIClient Gemini path: Vertex AI (server default)")
                    return genai.Client(
                        vertexai=True,
                        project=settings.GCP_PROJECT_ID,
                        location=settings.GCP_LOCATION,
                    )

                api_key = get_api_key(AIProvider.GEMINI)
                logger.info("AIClient Gemini path: Developer API (env key)")
                return genai.Client(api_key=api_key)
            except Exception as e:
                raise ValueError(Messages.AIProvider.INITIALIZATION_FAILED.format(
                    provider=self.provider, 
                    error=str(e)
                ))

        if self.provider == AIProvider.GROQ:
            try:
                api_key = self.api_key or get_api_key(AIProvider.GROQ)
                return Groq(api_key=api_key)
            except Exception as e:
                raise ValueError(Messages.AIProvider.INITIALIZATION_FAILED.format(
                    provider=self.provider, 
                    error=str(e)
                ))

        raise ValueError(Messages.AIProvider.UNSUPPORTED.format(provider=self.provider))

    @traceable
    def chat(self, prompt: str, **kwargs    ) -> str:
        """Send a chat request to the AI provider and return the response.
        
        This method sends the provided prompt to the configured AI provider
        with a system message that identifies the assistant as an expert code
        reviewer. The response is processed and returned as a string.
        
        Args:
            prompt (str): The user prompt or question to send to the AI provider.
                This should contain the code evaluation request or any other
                query for the AI assistant.
                
        Returns:
            str: The AI provider's response text. If the provider is not supported
            or an error occurs, returns "No response from AI".
            
        Example:
            >>> client = AIClient()
            >>> response = client.chat("Evaluate this Python code for best practices")
            >>> print(response)
            
        Note:
            The method uses a low temperature (0.1) and a maximum of 1000 tokens
            to ensure focused, concise responses suitable for code review tasks.
        """
        logger.debug(f"Provider is {self.provider}, model is {self.model}")
        run = get_current_run_tree()
        if run:
            run.name = f"{self.provider} - {self.model}"

        if self.provider == AIProvider.OPENAI:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer evaluating student projects against specific rubric criteria."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1000
            )
            return response.choices[0].message.content

        if self.provider == AIProvider.GEMINI:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    'temperature': 0
                }
            )
            return response.text

        if self.provider == AIProvider.GROQ:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer evaluating student projects against specific rubric criteria."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1000
            )
            return response.choices[0].message.content

        return "No response from AI"

