"""OS keychain storage interface for secrets received only from an official OAuth flow.

No login, OAuth endpoint, browser automation, or pasted-token API is implemented here.
"""
class SecureCredentialStore:
    def __init__(self, service: str="ai-quant-lab"):
        self.service=service
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("OS credential backend unavailable; credentials will not be stored insecurely") from exc
        self._keyring=keyring
        if not keyring.get_keyring().priority or keyring.get_keyring().__class__.__name__ in ("FailKeyring","NullKeyring"):
            raise RuntimeError("No secure OS keychain backend is available")
    def store_oauth_credential(self, account_ref: str, opaque_credential: str) -> None:
        if not account_ref or not opaque_credential: raise ValueError("account reference and OAuth credential required")
        self._keyring.set_password(self.service,account_ref,opaque_credential)
    def retrieve_for_authorized_client(self, account_ref: str) -> str | None:
        return self._keyring.get_password(self.service,account_ref)
    def delete(self, account_ref: str) -> None:
        try: self._keyring.delete_password(self.service,account_ref)
        except self._keyring.errors.PasswordDeleteError: pass
