"""
Chat API views.
"""
import json
import logging
from typing import Any

from django.http import JsonResponse, HttpResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from ...services.chat_service import ChatService
from ...services.session_service import SessionService

logger = logging.getLogger(__name__)


async def _stream_sse_response(
    request: HttpRequest,
    chat_service: ChatService,
    session,
    message: str,
    user_id: str,
    stream: bool = True,
    tenant_id: str | None = None,
    snapshot_id: str | None = None,
    config: dict | None = None,
) -> HttpResponse:
    """
    Stream chat response using Server-Sent Events (SSE).

    Sends HTTP headers for SSE, then streams tokens as they arrive
    from chat_service.stream_chat() async generator.
    """
    session_id = str(session.session_id)

    send = request.scope.get("_asgi_send")

    if not send:
        raise RuntimeError(
            "ASGI send not available. "
            "Ensure SSEStreamingMiddleware is installed in config/asgi.py"
        )

    # Send HTTP headers
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/event-stream"],
            [b"cache-control", b"no-cache"],
            [b"connection", b"keep-alive"],
        ],
    })

    try:
        # Stream tokens from chat_service
        async for chunk in chat_service.stream_chat(
            session=session,
            message=message,
            user_id=user_id,
            tenant_id=tenant_id,
            snapshot_id=snapshot_id,
            config=config,
        ):
            # Send SSE event with JSON data
            sse_data = f"data: {json.dumps(chunk)}\n\n"
            await send({
                "type": "http.response.body",
                "body": sse_data.encode("utf-8"),
                "more_body": True,
            })

        # Send [DONE] marker
        await send({
            "type": "http.response.body",
            "body": b"data: [DONE]\n\n",
            "more_body": False,
        })
    except Exception as e:
        logger.exception("SSE streaming error")
        # Send error event
        error_event = {"error": "An internal error occurred during streaming"}
        await send({
            "type": "http.response.body",
            "body": f"data: {json.dumps(error_event)}\n\n".encode("utf-8"),
            "more_body": False,
        })

    return HttpResponse()


async def _stream_sse_with_snapshot(
    request: HttpRequest,
    chat_service: ChatService,
    session,
    message: str,
    user_id: str,
    snapshot_id: str,
    tenant_id: str | None = None,
    config: dict | None = None,
) -> HttpResponse:
    """
    Stream chat response using a snapshot's frozen configuration (SSE).

    Like :func:`_stream_sse_response` but calls
    ``chat_service.stream_chat_with_snapshot()`` to fully honour the
    frozen snapshot configuration (skills, tools, etc.).
    """
    session_id = str(session.session_id)

    send = request.scope.get("_asgi_send")

    if not send:
        raise RuntimeError(
            "ASGI send not available. "
            "Ensure SSEStreamingMiddleware is installed in config/asgi.py"
        )

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/event-stream"],
            [b"cache-control", b"no-cache"],
            [b"connection", b"keep-alive"],
        ],
    })

    try:
        async for chunk in chat_service.stream_chat_with_snapshot(
            session=session,
            message=message,
            user_id=user_id,
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            config=config,
        ):
            sse_data = f"data: {json.dumps(chunk)}\n\n"
            await send({
                "type": "http.response.body",
                "body": sse_data.encode("utf-8"),
                "more_body": True,
            })

        await send({
            "type": "http.response.body",
            "body": b"data: [DONE]\n\n",
            "more_body": False,
        })
    except Exception as e:
        logger.exception("SSE streaming error (snapshot)")
        error_event = {"error": "An internal error occurred during streaming"}
        await send({
            "type": "http.response.body",
            "body": f"data: {json.dumps(error_event)}\n\n".encode("utf-8"),
            "more_body": False,
        })

    return HttpResponse()


@method_decorator(csrf_exempt, name='dispatch')
class ChatView(View):
    """
    Handle chat requests (supports both non-streaming and SSE streaming).

    POST /chatbot/api/chat/

    Query Parameters:
        stream: bool - If True, use SSE streaming; otherwise return full response

    Request Body:
        session_id: str - Session identifier
        message: str - User message
        user_id: str - User identifier (optional)
        stream: bool - Enable streaming (optional)
    """

    async def post(self, request: HttpRequest) -> HttpResponse:
        """Process a chat message and return response."""
        try:
            data = json.loads(request.body)

            session_id = data.get('session_id')
            message = data.get('message', '')
            user_id = data.get('user_id', 'anonymous')
            stream = data.get('stream', False)
            snapshot_id = data.get('snapshot_id')
            use_snapshot_config = data.get('use_snapshot_config', False)
            config = data.get('config')

            if not message:
                return JsonResponse({
                    'error': 'Message is required'
                }, status=400)

            if not session_id:
                return JsonResponse({
                    'error': 'session_id is required. Please create a session first using POST /chatbot/api/sessions/'
                }, status=400)

            session_service = SessionService()
            session = await session_service.get_session(session_id)
            if not session:
                return JsonResponse({
                    'error': 'Session not found'
                }, status=404)

            # Process chat
            chat_service = ChatService()
            # Get tenant_id from request (set by TokenAuthMiddleware)
            tenant_id = getattr(request, 'tenant_id', None)
            logger.debug("chat session: %s", session)

            # ── Snapshot config path (fully honours frozen skills/tools) ──
            if snapshot_id and use_snapshot_config:
                if stream:
                    return await _stream_sse_with_snapshot(
                        request=request,
                        chat_service=chat_service,
                        session=session,
                        message=message,
                        user_id=user_id,
                        snapshot_id=snapshot_id,
                        tenant_id=tenant_id,
                        config=config,
                    )
                else:
                    result = await chat_service.chat_with_snapshot(
                        session=session,
                        message=message,
                        user_id=user_id,
                        snapshot_id=snapshot_id,
                        tenant_id=tenant_id,
                    )
                    return JsonResponse({
                        'session_id': str(session.session_id),
                        'external_session_id': session.external_session_id,
                        'message_id': result.get('message_id'),
                        'content': result.get('content'),
                        'trace': result.get('trace', []),
                        'usage': result.get('usage', {}),
                    })

            # ── Normal chat path (with optional fallback snapshot) ──
            if stream:
                return await _stream_sse_response(
                    request=request,
                    chat_service=chat_service,
                    session=session,
                    message=message,
                    user_id=user_id,
                    stream=True,
                    tenant_id=tenant_id,
                    snapshot_id=snapshot_id,
                    config=config,
                )
            else:
                result = await chat_service.chat(
                    session=session,
                    message=message,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    snapshot_id=snapshot_id,
                )

                return JsonResponse({
                    'session_id': str(session.session_id),
                    'external_session_id': session.external_session_id,
                    'message_id': result.get('message_id'),
                    'content': result.get('content'),
                    'trace': result.get('trace', []),
                    'usage': result.get('usage', {})
                })

        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Invalid JSON'
            }, status=400)
        except Exception as e:
            logger.exception("Chat error")
            return JsonResponse({
                'error': 'An internal error occurred'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ChatInterruptView(View):
    """
    Handle chat interrupt requests.

    POST /chatbot/api/chat/interrupt/

    Request Body:
        session_id: str - Session to interrupt
    """

    async def post(self, request: HttpRequest) -> JsonResponse:
        """Interrupt an active streaming session."""
        try:
            data = json.loads(request.body)

            session_id = data.get('session_id')
            interrupt_message = data.get('interrupt_message', '')

            if not session_id:
                return JsonResponse({
                    'error': 'session_id is required'
                }, status=400)

            session_service = SessionService()
            session = await session_service.get_session(session_id)
            if not session:
                return JsonResponse({
                    'error': 'Session not found'
                }, status=404)

            chat_service = ChatService()
            interrupted = await chat_service.interrupt_session(
                session_id=session_id,
                interrupt_message=interrupt_message,
            )

            return JsonResponse({
                'interrupted': interrupted,
                'session_id': session_id,
                'external_session_id': session.external_session_id,
            })

        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Invalid JSON'
            }, status=400)
        except Exception as e:
            logger.exception("Chat interrupt error")
            return JsonResponse({
                'error': 'An internal error occurred'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class BatchChatView(View):
    """
    Handle batch chat requests (multiple questions, one answer).
    
    POST /chatbot/api/chat/batch/
    """
    
    async def post(self, request: HttpRequest) -> JsonResponse:
        """Process multiple messages and return combined response."""
        try:
            data = json.loads(request.body)

            session_id = data.get('session_id')
            messages = data.get('messages', [])
            user_id = data.get('user_id', 'anonymous')
            group_id = data.get('group_id')

            if not messages:
                return JsonResponse({
                    'error': 'Messages are required'
                }, status=400)

            if not session_id:
                return JsonResponse({
                    'error': 'session_id is required. Please create a session first using POST /chatbot/api/sessions/'
                }, status=400)

            session_service = SessionService()
            session = await session_service.get_session(session_id)
            if not session:
                return JsonResponse({
                    'error': 'Session not found'
                }, status=404)
            
            # Process batch chat
            chat_service = ChatService()
            # Get tenant_id from request (set by TenantMiddleware)
            tenant_id = getattr(request, 'tenant_id', None)

            result = await chat_service.batch_chat(
                session=session,
                messages=messages,
                user_id=user_id,
                group_id=group_id,
                tenant_id=tenant_id,
            )
            
            return JsonResponse({
                'session_id': str(session.session_id),
                'external_session_id': session.external_session_id,
                'group_id': result.get('group_id'),
                'message_id': result.get('message_id'),
                'content': result.get('content'),
                'trace': result.get('trace', []),
                'usage': result.get('usage', {})
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Invalid JSON'
            }, status=400)
        except Exception as e:
            logger.exception("Batch chat error")
            return JsonResponse({
                'error': 'An internal error occurred'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ToolConfirmView(View):
    """Handle tool confirmation responses (for SSE/HTTP mode).

    POST /chatbot/api/chat/confirm/

    Request Body:
        confirmation_id: str — the confirmation ID from tool_confirm_request
        approved: bool — whether the user approved the tool execution
    """

    async def post(self, request: HttpRequest) -> JsonResponse:
        """Process a tool confirmation response."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        confirmation_id = data.get('confirmation_id', '').strip()
        approved = data.get('approved', False)

        if not confirmation_id:
            return JsonResponse({'error': 'confirmation_id is required'}, status=400)

        from ...agent.hooks.confirmation_store import get_confirmation_store
        store = get_confirmation_store()
        success = await store.respond(confirmation_id, approved)

        if not success:
            return JsonResponse(
                {'confirmed': False, 'error': 'Confirmation not found or already resolved'},
                status=404,
            )

        return JsonResponse({'confirmed': True})
