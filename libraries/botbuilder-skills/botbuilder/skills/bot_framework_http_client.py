# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from typing import Dict
import requests

from botbuilder.core import InvokeResponse
from botbuilder.schema import Activity
from botframework.connector.auth import (
    ChannelProvider,
    CredentialProvider,
    GovernmentConstants,
    MicrosoftAppCredentials,
)

# from .referr_info import ReferrInfo
from .skill_conversation import SkillConversation


class BotFrameworkHttpClient:

    """
    A skill host adapter implements API to forward activity to a skill and
    implements routing ChannelAPI calls from the Skill up through the bot/adapter.
    """

    INVOKE_ACTIVITY_NAME = "SkillEvents.ChannelApiInvoke"
    _BOT_IDENTITY_KEY = "BotIdentity"
    _APP_CREDENTIALS_CACHE: Dict[str:MicrosoftAppCredentials] = {}

    def __init__(
        self,
        credential_provider: CredentialProvider,
        channel_provider: ChannelProvider = None,
        logger: object = None,
    ):
        if not credential_provider:
            raise TypeError("credential_provider can't be None")

        self._credential_provider = credential_provider
        self._channel_provider = channel_provider
        self._logger = logger

    async def post_activity(
        self,
        from_bot_id: str,
        to_bot_id: str,
        to_url: str,
        service_url: str,
        conversation_id: str,
        activity: Activity,
    ) -> InvokeResponse:
        app_credentials = await self._get_app_credentials(from_bot_id, to_bot_id)

        if not app_credentials:
            raise RuntimeError("Unable to get appCredentials to connect to the skill")

        # Get token for the skill call
        token = app_credentials.get_access_token()

        # Capture current activity settings before changing them.
        # TODO: DO we need to set the activity ID? (events that are created manually don't have it).
        original_conversation_id = activity.conversation.id
        original_service_url = activity.service_url

        try:
            # TODO: figure out a better way of passing the original ServiceUrl when calling
            # the skill so we don't have to encode it in the conversation ID.
            # Encode original bot service URL and ConversationId in the new conversation ID so we can unpack it later.
            skill_conversation = SkillConversation(
                service_url=activity.service_url, conversation_id=conversation_id
            )
            activity.conversation.id = skill_conversation.get_skill_conversation_id()
            activity.service_url = service_url

            # TODO: Review the rest of the code and see if we can remove this. Gabo
            # TODO: can we use this property back to store the source conversation ID and the ServiceUrl?
            """
            activity.recipient.properties["skillId"] = to_bot_id
            referr = ReferrInfo(
                from_bot_id=from_bot_id,
                to_bot_id=to_bot_id,
                conversation_id=original_conversation_id,
                service_url=original_service_url
            )

            activity.recipient.properties[ReferrInfo.KEY] = referr.serialize()
            """
            json_content = json.dumps(activity.serialize())
            with requests.Session() as session:
                resp = session.post(
                    to_url,
                    data=json_content.encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer:{token}",
                        "Content-type": "application/json; charset=utf-8",
                    },
                )
                resp.raise_for_status()
                content = resp.json

                if content:
                    return InvokeResponse(status=resp.status_code, body=content)

        finally:
            # Restore activity properties.
            activity.conversation.id = original_conversation_id
            activity.service_url = original_service_url

    async def _get_app_credentials(
        self, app_id: str, oauth_scope: str
    ) -> MicrosoftAppCredentials:
        if not app_id:
            return MicrosoftAppCredentials(None, None)

        cache_key = f"{app_id}{oauth_scope}"
        app_credentials = BotFrameworkHttpClient._APP_CREDENTIALS_CACHE.get(cache_key)

        if app_credentials:
            return app_credentials

        app_password = await self._credential_provider.get_app_password(app_id)
        app_credentials = MicrosoftAppCredentials(
            app_id, app_password, oauth_scope=oauth_scope
        )
        if self._channel_provider.is_government():
            app_credentials.oauth_endpoint = (
                GovernmentConstants.TO_CHANNEL_FROM_BOT_LOGIN_URL
            )
            app_credentials.oauth_scope = (
                GovernmentConstants.TO_CHANNEL_FROM_BOT_OAUTH_SCOPE
            )

        BotFrameworkHttpClient._APP_CREDENTIALS_CACHE[cache_key] = app_credentials
        return app_credentials