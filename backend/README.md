# Backend

The backend is the **zero-nvr control plane**.

It will own:

- canonical domain models;
- camera and connection lifecycle;
- recording policies and recording metadata;
- event normalization and alert rules;
- storage/upload orchestration;
- playback timeline and authorization;
- runtime health and audit APIs;
- adapters to external protocol/media/infrastructure components.

It should **not** reimplement:

- RTSP/WebRTC/HLS media servers;
- ONVIF SOAP/WSDL stacks;
- vendor private protocols when an official SDK exists;
- generic cloud-drive protocols;
- full AI inference platforms.

External systems are accessed through explicit adapter contracts.
