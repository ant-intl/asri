"""
Chat Agent implementation.

Uses pipecat's Frame-based Pipeline with LLM native function_calling
for tool execution. Creates a per-request Pipeline that bridges to
ASRI's LLM providers, ActionExecutor, and existing registries.
"""
import asyncio
import json
import logging
from typing import Dict, Any, List, AsyncGenerator, Optional

from ..pipeline.framework import (
    StartFrame,
    LLMMessagesAppendFrame,
    LLMStartFrame,
    LLMEndFrame,
    FrameDirection,
    FunctionSchema,
    FunctionCallParams,
)

from ..agent.base import BaseAgent
from ..agent.context import AgentContext
from ..executor.action_executor import ActionExecutor
from ..pipeline.functions.tool_functions import (
    build_tool_schemas,
    build_function_handlers,
)
from ..pipeline.processors.output_collector import OutputCollectorProcessor
from ..pipeline.processors.full_duplex_llm_processor import FullDuplexLLMProcessor
from ..pipeline.processors.async_executor import AsyncExecutorProcessor
from ..prompts import BaseSystemPrompt
from ...integrations.llm.base import BaseLLMProvider
from ...tenant.config import get_chatbot_config

logger = logging.getLogger(__name__)


class ChatAgent(BaseAgent):
    """Unified chat agent using pipecat Frame-based Pipeline.

    Supports both LLM native function_calling (tool_calls) and text-based
    tool calling (e.g. interleaved thinking with <tool_call> tags).
    Creates a fresh Pipeline per request with conversation history injected
    into the LLM context.
    """

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        system_prompt: str | None = None,
        prompt: BaseSystemPrompt | None = None,
        max_iterations: int | None = None,
        tenant_id: str | None = None,
        frozen_skills: list[dict] | None = None,
        frozen_tools: list[dict] | None = None,
        interrupt_strategy: str | None = None,
        execution_mode: str = 'interleaved',
        **kwargs,
    ):
        """Initialize ChatAgent.

        Args:
            llm_provider: ASRI LLM provider for chat completions.
            system_prompt: Optional system prompt override.  When set,
                ``prompt`` is not needed (message building bypasses the
                prompt class entirely).
            prompt: A loaded :class:`BaseSystemPrompt` instance.  Required
                when ``system_prompt`` is not provided.
            max_iterations: Maximum number of tool-call rounds.
                Falls back to tenant config REACT_MAX_ITERATIONS (default 10).
            tenant_id: Optional tenant ID for tool/skill isolation.
            frozen_skills: Optional skill list from a snapshot. When set,
                ``_load_skills()`` returns these instead of querying the
                live registry, enabling frozen snapshot behaviour.
            frozen_tools: Optional tool schemas from a snapshot. When set,
                ``_load_tool_schemas()`` returns these instead of querying
                the live registry.
            execution_mode: Execution mode - 'interleaved' or 'standard'.
                Controls whether intermediate answers are emitted and
                whether tools are executed concurrently.
        """
        super().__init__(**kwargs)
        self.llm_provider = llm_provider
        self._custom_system_prompt = system_prompt
        self._prompt = prompt
        self._tenant_id = tenant_id
        self._frozen_skills = frozen_skills
        self._frozen_tools = frozen_tools
        self._execution_mode = execution_mode

        # Validate: need either system_prompt or prompt
        if not self._custom_system_prompt and not self._prompt:
            raise ValueError(
                "Either system_prompt or prompt must be provided."
            )

        chatbot_config = get_chatbot_config()
        self.max_iterations = max_iterations or chatbot_config.get(
            'REACT_MAX_ITERATIONS', 10
        )

        # Load tool interrupt strategy configuration
        # Priority: constructor argument > chatbot config env var > default
        self._interrupt_strategy = (
            interrupt_strategy
            or chatbot_config.get('TOOL_INTERRUPT_STRATEGY', 'none')
        )

    async def run(
        self,
        query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> Dict[str, Any]:
        """Run the Chat agent to completion.

        Args:
            query: User's query/question.
            history: Conversation history messages.
            context: Optional pre-configured context.

        Returns:
            Dict with 'answer', 'trace', 'context_messages', 'system_prompt', 'tools',
            'prompt_tokens', 'completion_tokens', 'total_tokens', 'model'.
        """
        # Get system prompt from prompt (must be provided at construction)
        if context is None:
            context = AgentContext()

        context.current_query = query
        context.tenant_id = self._tenant_id

        queue, llm_processor = await self._build_pipeline(context)

        # Render system prompt: use custom string or render from prompt class
        if self._custom_system_prompt:
            system_prompt = self._custom_system_prompt
        else:
            prompt = self._prompt
            system_prompt = prompt.render(
                skills=self._load_skills() if prompt.requires_skills() else None,
                user_context=context.user_context,
            )

        # Get actual tool schemas
        tool_schemas = self._load_tool_schemas() or []

        # Pass query and history to pipeline (let processor build messages internally)
        frame = LLMMessagesAppendFrame(
            query=query,
            history=history or [],
            run_llm=True
        )

        # Run the pipeline in a background task
        pipeline_task = asyncio.create_task(
            self._drive_pipeline(llm_processor, frame, queue)
        )

        # Collect all output from the queue
        answer_parts: list[str] = []
        cards: list[dict] = []
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    continue
                chunk_type = chunk.get('type', '')
                if chunk_type == 'done':
                    break
                if chunk_type == 'answer':
                    answer_parts.append(chunk.get('content', ''))
                    # Add to trace for display (consistent with SSE streaming)
                    context.add_trace('answer', content=chunk.get('content'))
                elif chunk_type in ('tool_call', 'tool_result'):
                    context.add_trace(
                        chunk_type,
                        content=chunk.get('content'),
                        status=chunk.get('status'),
                        tool_name=chunk.get('tool_name'),
                        parameters=chunk.get('parameters'),
                        result=chunk.get('result'),
                        tool_call_id=chunk.get('tool_call_id'),
                    )
                elif chunk_type == 'think':
                    # Think chunks are already parsed by LLM processor
                    context.add_trace('thinking', content=chunk.get('content'))
                elif chunk_type == 'card':
                    card_data = chunk.get('card_data', {})
                    if card_data:
                        cards.append(card_data)

        except Exception as e:
            logger.exception(f"Error collecting pipeline output: {e}")
        finally:
            if not pipeline_task.done():
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except asyncio.CancelledError:
                    pass

        return {
            'answer': ''.join(answer_parts),
            'trace': context.trace,
            'context_messages': llm_processor.get_context_messages(),
            'system_prompt': system_prompt,
            'tools': tool_schemas,
            'cards': cards,
            'prompt_tokens': context.prompt_tokens,
            'completion_tokens': context.completion_tokens,
            'total_tokens': context.get_total_tokens(),
            'model': self.llm_provider.get_model_name(),
            'has_error': llm_processor.has_error(),
            'error_message': llm_processor.get_error_message(),
        }

    async def stream(
        self,
        query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream the Chat agent's response.

        Args:
            query: User's query/question.
            history: Conversation history messages.
            context: Optional pre-configured context.

        Yields:
            Dict chunks with 'type' and 'content'.
        """
        if context is None:
            context = AgentContext()

        context.current_query = query
        context.tenant_id = self._tenant_id

        queue, llm_processor = await self._build_pipeline(context)
        
        # Store reference for external context retrieval
        self._last_llm_processor = llm_processor

        # Pass query and history to pipeline
        frame = LLMMessagesAppendFrame(
            query=query,
            history=history or [],
            run_llm=True
        )

        # Run the pipeline in a background task
        pipeline_task = asyncio.create_task(
            self._drive_pipeline(llm_processor, frame, queue)
        )

        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    continue
                chunk_type = chunk.get('type', '')
                if chunk_type == 'done':
                    break

                if chunk_type == 'think':
                    # Think chunks are already parsed by LLM processor
                    context.add_trace('thinking', content=chunk.get('content'))
                    yield chunk
                elif chunk_type in ('tool_call', 'tool_result'):
                    # Record trace for tool events
                    # context.add_trace(
                    #     chunk_type,
                    #     content=chunk.get('content'),
                    #     status=chunk.get('status'),
                    #     tool_name=chunk.get('tool_name'),
                    #     parameters=chunk.get('parameters'),
                    #     result=chunk.get('result'),
                    #     tool_call_id=chunk.get('tool_call_id'),
                    # )
                    yield chunk
                elif chunk_type == 'llm_start':
                    # LLM start event
                    yield chunk
                elif chunk_type == 'llm_end':
                    # LLM end event with usage stats
                    yield chunk
                elif chunk_type == 'card':
                    # Card data for frontend rendering (bypasses LLM context)
                    yield chunk
                else:
                    # Pass through answer and other chunks directly
                    yield chunk
        except Exception as e:
            logger.exception(f"Error streaming pipeline output: {e}")
            yield {'type': 'error', 'content': str(e)}
        finally:
            if not pipeline_task.done():
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except asyncio.CancelledError:
                    pass

        # Yield done with complete context messages for persistence
        context_messages = llm_processor.get_context_messages()
        yield {'type': 'done', 'content': '', 'context_messages': context_messages}

    async def get_context_messages(self) -> List[Dict[str, Any]] | None:
        """Get current accumulated context messages from LLM processor."""
        if hasattr(self, '_last_llm_processor') and self._last_llm_processor:
            return self._last_llm_processor.get_context_messages()
        return None

    def _build_messages(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> list[dict]:
        """Build the full messages list for the LLM call.

        Delegates to the prompt's build_messages() so each prompt mode
        can define its own message structure.

        Args:
            query: Current user query.
            history: Previous conversation messages.

        Returns:
            Messages list (structure depends on prompt mode).
        """
        if self._custom_system_prompt:
            # Custom system prompt bypasses prompt class entirely
            messages = [{'role': 'system', 'content': self._custom_system_prompt}]
            if history:
                messages.extend(history)
            messages.append({'role': 'user', 'content': query})
            return messages

        prompt = self._prompt
        skills = self._load_skills()
        tool_schemas = self._load_tool_schemas()

        # When native tools are sent via API (auto_tools=True), don't inject
        # tool_schemas into the system prompt to avoid conflict with the
        # text-based <tool_call> instruction.
        auto_tools = getattr(self.llm_provider, 'auto_tools', False)
        prompt_tool_schemas = None if auto_tools else tool_schemas

        return prompt.build_messages(
            query=query,
            history=history,
            skills=skills,
            tool_schemas=prompt_tool_schemas,
        )

    def _load_skills(self) -> list[dict] | None:
        """Load skill list for prompt injection when the prompt requires it."""
        if self._frozen_skills is not None:
            logger.info(
                f"_load_skills: returning {len(self._frozen_skills)} frozen skills "
                f"from snapshot"
            )
            return self._frozen_skills
        prompt = self._prompt
        if not prompt.requires_skills():
            logger.info(f"_load_skills: prompt={prompt.__class__.__name__}, requires_skills=False, returning None")
            return None
        from ...integrations.skill.registry import SkillRegistry
        skills = SkillRegistry.list_skills_with_descriptions(tenant_id=self._tenant_id)
        logger.info(
            f"_load_skills: tenant_id={self._tenant_id}, "
            f"prompt={prompt.__class__.__name__}, "
            f"skills_count={len(skills)}, "
            f"skills={[(s['name'], s['description'][:50]) for s in skills]}"
        )
        return skills

    def _load_tool_schemas(self) -> list[dict] | None:
        """Load tool schema list for prompt injection."""
        if self._frozen_tools is not None:
            logger.info(
                f"_load_tool_schemas: returning {len(self._frozen_tools)} frozen tools "
                f"from snapshot"
            )
            return self._frozen_tools
        from ...integrations.tool.base import ToolRegistry
        # Pass tenant_id from context to load tenant-specific tools
        tenant_id = getattr(self, '_tenant_id', None)
        schemas = ToolRegistry.list_tools_with_schemas(tenant_id=tenant_id)
        return schemas

    async def _build_pipeline(
        self,
        context: AgentContext,
    ) -> tuple[asyncio.Queue, FullDuplexLLMProcessor]:
        """Build linked pipecat processors for a single request.

        Creates FullDuplexLLMProcessor -> OutputCollectorProcessor chain
        with AsyncExecutorProcessor for non-blocking tool execution.

        When the prompt uses text-based tool calling (e.g. interleaved
        thinking with ``<tool_call>`` tags), content_extractor and
        output_mapper are used for parsing; native function_calling is
        skipped.

        Args:
            context: Agent context with capability flags.

        Returns:
            Tuple of (output_queue, llm_processor).
        """
        executor = ActionExecutor(
            hook_manager=getattr(context, 'hook_manager', None)
        )

        # Build function handlers (always needed for execution)
        handlers = build_function_handlers(executor, context)

        # Always use interleaved mode: tools are embedded in the user message
        # by build_messages(); extractor/mapper parse text-based tool calls.
        # Get extractor config from prompt (priority: DB template > class default)
        from ..parsers import OutputParserFactory

        if self._custom_system_prompt:
            # system_prompt string path: use default extractor config
            parser_cfg = {
                'extractor': {'type': 'xml_tags', 'default_type': 'think'},
                'mapper': {
                    'tool_keys': ['tool_call'],
                    'think_keys': ['think'],
                    'answer_keys': ['answer'],
                },
            }
            extractor_cfg = parser_cfg['extractor']
            mapper_cfg = parser_cfg['mapper']
            content_extractor, output_mapper = OutputParserFactory.create(
                extractor_cfg, mapper_cfg
            )
            observation_formatter = lambda obs: {'role': 'user', 'content': f'Observation: {obs}'}
            build_prompt_messages = self._build_messages
        else:
            prompt = self._prompt
            parser_cfg = await prompt.get_extractor_config_async()
            extractor_cfg = parser_cfg.get('extractor', {
                'type': 'xml_tags',
                'default_type': 'think',
            })
            mapper_cfg = parser_cfg.get('mapper', {
                'tool_keys': ['tool_call'],
                'think_keys': ['think'],
                'answer_keys': ['answer'],
            })
            content_extractor, output_mapper = OutputParserFactory.create(
                extractor_cfg, mapper_cfg
            )
            observation_formatter = prompt.format_observation
            build_prompt_messages = prompt.build_messages
        tool_schemas = self._load_tool_schemas()
        skills = self._load_skills()
        auto_tools = getattr(self.llm_provider, 'auto_tools', False)

        # auto_tools from llm_provider config controls whether to also
        # pass OpenAI native tools parameter (in addition to prompt embedding)
        tools_payload = None
        if auto_tools:
            schemas = build_tool_schemas(context)
            tools_payload = FullDuplexLLMProcessor.build_tools_payload(schemas) if schemas else None

        # When native tools are sent via API (auto_tools=True), don't inject
        # tool_schemas into the system prompt text — the API's tools parameter
        # already exposes the full schemas. This avoids conflict between the
        # text-based <tool_call> instruction and native function calling.
        if auto_tools:
            tool_schemas = None

        # Determine execution mode settings
        is_interleaved = self._execution_mode == 'interleaved'

        # Create output queue and collector
        output_queue: asyncio.Queue = asyncio.Queue()
        output_collector = OutputCollectorProcessor(
            output_queue=output_queue,
            enable_direct_mode=True,
        )

        # Create async executor for non-blocking tool calls
        async_executor = AsyncExecutorProcessor(
            handlers=handlers,
            enable_direct_mode=True,
            enable_concurrent=is_interleaved,
        )

        # Create full-duplex LLM processor
        llm_processor = FullDuplexLLMProcessor(
            llm_provider=self.llm_provider,
            tools_payload=tools_payload,
            function_handlers=handlers,
            context=context,
            content_extractor=content_extractor,
            output_mapper=output_mapper,
            observation_formatter=observation_formatter,
            max_iterations=self.max_iterations,
            enable_direct_mode=True,
            enable_concurrent_tools=is_interleaved,
            enable_interleaved_output=is_interleaved,
            build_prompt_messages=build_prompt_messages,
            tool_schemas=tool_schemas,
            skills=skills,
            interrupt_strategy=self._interrupt_strategy,
        )

        # Register async executor with LLM processor
        llm_processor.register_async_executor(async_executor)

        # Link async_executor -> llm_processor for result callbacks
        async_executor.link(llm_processor)

        # Link processors: LLM -> OutputCollector
        # Async executor results are pushed back to LLM via callbacks
        llm_processor.link(output_collector)

        logger.debug("Built full-duplex pipeline with async executor")

        return output_queue, llm_processor

    @staticmethod
    async def _drive_pipeline(
        llm_processor: FullDuplexLLMProcessor,
        frame: LLMMessagesAppendFrame,
        queue: asyncio.Queue,
    ) -> None:
        """Drive the processor chain by pushing frames through it.

        Sends a StartFrame to initialize processors, then pushes
        the LLMMessagesAppendFrame to trigger the LLM call.

        Args:
            llm_processor: Head of the processor chain.
            frame: LLMMessagesAppendFrame with query/history or messages.
            queue: Output queue (for sending sentinel on completion).
        """
        try:
            # Initialize the processor chain with StartFrame
            await llm_processor.process_frame(
                StartFrame(), FrameDirection.DOWNSTREAM
            )
            # Push the actual message frame
            await llm_processor.process_frame(
                frame, FrameDirection.DOWNSTREAM
            )
        except Exception as e:
            logger.exception(f"Pipeline execution error: {e}")
            await queue.put({'type': 'error', 'content': str(e)})
        finally:
            # Always send sentinel so the consumer knows we're done
            await queue.put(None)
