# ── Config ────────────────────────────────────────────────────────────────────
-include config.mk
APP_DIR        ?= $(error APP_DIR not set — copy config.mk.example to config.mk)
AWS_ACCOUNT_ID ?= $(error AWS_ACCOUNT_ID not set — copy config.mk.example to config.mk)
API_URL        ?= $(error API_URL not set — copy config.mk.example to config.mk)
AUTH_TOKEN     ?= $(error AUTH_TOKEN not set — copy config.mk.example to config.mk)
BUCKET         ?= $(error BUCKET not set — copy config.mk.example to config.mk)

AWS_REGION        := ap-southeast-1
ECR_REGISTRY      := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
STATE_MACHINE_ARN := arn:aws:states:$(AWS_REGION):$(AWS_ACCOUNT_ID):stateMachine:metadata-extraction-orchestrator

env  ?= dev
TYPE ?= VIDEO

ecr_uri   = $(ECR_REGISTRY)/metadata-extraction/$(1):latest
lambda_fn = function-metadata-extraction-$(1)-$(env)

# ── Phony targets ──────────────────────────────────────────────────────────────
.PHONY: \
    help \
    ecr-login \
    deploy-lambda \
    deploy-asr \
    deploy-intelligent-frame-sampling \
    _bda-image-engine-push deploy-bda-image-engine-invoke deploy-bda-image-engine-process \
    _bda-video-engine-push deploy-bda-video-engine-invoke deploy-bda-video-engine-process \
    content-create content-create-all \
    content-trigger content-create-and-trigger content-trigger-all

# ── Help ───────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "MEP Deploy — available targets"
	@echo ""
	@echo "  Deploy"
	@echo "    ecr-login                          Log in to ECR"
	@echo "    deploy-lambda service=<name>       Build + push Lambda image, update function [env=dev]"
	@echo "    deploy-asr                         Build + push ECS automated-speech-recognition"
	@echo "    deploy-intelligent-frame-sampling  Build + push ECS mdm-intelligent-frame-sampling"
	@echo "    deploy-bda-image-engine-invoke     Build + push BDA image engine invoke Lambda"
	@echo "    deploy-bda-image-engine-process    Build + push BDA image engine process Lambda"
	@echo "    deploy-bda-video-engine-invoke     Build + push BDA video engine invoke Lambda"
	@echo "    deploy-bda-video-engine-process    Build + push BDA video engine process Lambda"
	@echo ""
	@echo "  Content testing"
	@echo "    content-create TYPE=<type>         Create one content record + copy media [VIDEO|IMAGE|AUDIO|TEXT]"
	@echo "    content-create-all                 Create content records for all four types"
	@echo "    content-trigger CONTENT_ID=<id> CONTENT_TYPE=<type>  Trigger Step Functions workflow"
	@echo "    content-create-and-trigger TYPE=<type>               Create then immediately trigger"
	@echo "    content-trigger-all                Create + trigger all four types"
	@echo ""

# ── ECR ───────────────────────────────────────────────────────────────────────
ecr-login:
	@aws ecr get-login-password --region $(AWS_REGION) \
	    | docker login --username AWS --password-stdin $(ECR_REGISTRY)

define ensure-ecr-repo
	@aws ecr describe-repositories \
	    --repository-names metadata-extraction/$(1) \
	    --region $(AWS_REGION) > /dev/null 2>&1 \
	  || aws ecr create-repository \
	        --repository-name metadata-extraction/$(1) \
	        --region $(AWS_REGION) \
	        --image-scanning-configuration scanOnPush=true
endef

# ── Lambda ─────────────────────────────────────────────────────────────────────
# make deploy-lambda service=<name> [env=dev]
deploy-lambda:
	@[ -n "$(service)" ] || { echo "ERROR: service is required"; exit 1; }
	$(call ensure-ecr-repo,$(service))
	@aws lambda get-function \
	    --function-name $(call lambda_fn,$(service)) \
	    --region $(AWS_REGION) > /dev/null 2>&1 \
	  || { echo "ERROR: $(call lambda_fn,$(service)) does not exist"; exit 1; }
	docker buildx build \
	    -f $(APP_DIR)/services/$(service)/Dockerfile \
	    --platform linux/arm64 --provenance=false --load \
	    -t $(call ecr_uri,$(service)) $(APP_DIR)
	docker push $(call ecr_uri,$(service))
	aws lambda update-function-code \
	    --function-name $(call lambda_fn,$(service)) \
	    --image-uri $(call ecr_uri,$(service)) \
	    --region $(AWS_REGION)
	@echo "Deploy complete: $(call ecr_uri,$(service)) -> $(call lambda_fn,$(service))"


# ── ECS: automated-speech-recognition (arm64) ─────────────────────────────────
deploy-asr:
	$(call ensure-ecr-repo,automated-speech-recognition)
	docker buildx build \
	    -f $(APP_DIR)/services/automated-speech-recognition/Dockerfile \
	    --platform linux/arm64 --provenance=false --load \
	    -t $(call ecr_uri,automated-speech-recognition) $(APP_DIR)
	docker push $(call ecr_uri,automated-speech-recognition)
	@echo "Deploy complete: $(call ecr_uri,automated-speech-recognition)"


# ── ECS: mdm-intelligent-frame-sampling (amd64) ───────────────────────────────
deploy-intelligent-frame-sampling:
	$(call ensure-ecr-repo,mdm-intelligent-frame-sampling)
	docker buildx build \
	    -f $(APP_DIR)/services/mdm-intelligent-frame-sampling/Dockerfile \
	    --platform linux/amd64 --provenance=false --load \
	    -t $(call ecr_uri,mdm-intelligent-frame-sampling) $(APP_DIR)
	docker push $(call ecr_uri,mdm-intelligent-frame-sampling)
	@echo "Deploy complete: $(call ecr_uri,mdm-intelligent-frame-sampling)"


# ── BDA Image Engine (two Lambdas, one shared image) ──────────────────────────
BDA_IE_IMAGE   := $(call ecr_uri,bda-image-engine)
BDA_IE_INVOKE  := function-metadata-extraction-bda-image-engine-invoke-$(env)
BDA_IE_PROCESS := function-metadata-extraction-bda-image-engine-process-$(env)

_bda-image-engine-push:
	$(call ensure-ecr-repo,bda-image-engine)
	docker buildx build \
	    -f $(APP_DIR)/services/bda-image-engine/Dockerfile \
	    --platform linux/arm64 --provenance=false --load \
	    -t $(BDA_IE_IMAGE) $(APP_DIR)
	docker push $(BDA_IE_IMAGE)

deploy-bda-image-engine-invoke: _bda-image-engine-push
	@aws lambda get-function --function-name $(BDA_IE_INVOKE) --region $(AWS_REGION) > /dev/null 2>&1 \
	  || { echo "ERROR: $(BDA_IE_INVOKE) does not exist"; exit 1; }
	aws lambda update-function-code \
	    --function-name $(BDA_IE_INVOKE) --image-uri $(BDA_IE_IMAGE) --region $(AWS_REGION)
	@echo "Deploy complete: $(BDA_IE_IMAGE) -> $(BDA_IE_INVOKE)"

deploy-bda-image-engine-process: _bda-image-engine-push
	@aws lambda get-function --function-name $(BDA_IE_PROCESS) --region $(AWS_REGION) > /dev/null 2>&1 \
	  || { echo "ERROR: $(BDA_IE_PROCESS) does not exist"; exit 1; }
	aws lambda update-function-code \
	    --function-name $(BDA_IE_PROCESS) --image-uri $(BDA_IE_IMAGE) --region $(AWS_REGION)
	@echo "Deploy complete: $(BDA_IE_IMAGE) -> $(BDA_IE_PROCESS)"


# ── BDA Video Engine (two Lambdas, one shared image) ──────────────────────────
BDA_VE_IMAGE   := $(call ecr_uri,bda-video-engine)
BDA_VE_INVOKE  := function-metadata-extraction-bda-video-engine-invoke-$(env)
BDA_VE_PROCESS := function-metadata-extraction-bda-video-engine-process-$(env)

_bda-video-engine-push:
	$(call ensure-ecr-repo,bda-video-engine)
	docker buildx build \
	    -f $(APP_DIR)/services/bda-video-engine/Dockerfile \
	    --platform linux/arm64 --provenance=false --load \
	    -t $(BDA_VE_IMAGE) $(APP_DIR)
	docker push $(BDA_VE_IMAGE)

deploy-bda-video-engine-invoke: _bda-video-engine-push
	@aws lambda get-function --function-name $(BDA_VE_INVOKE) --region $(AWS_REGION) > /dev/null 2>&1 \
	  || { echo "ERROR: $(BDA_VE_INVOKE) does not exist"; exit 1; }
	aws lambda update-function-code \
	    --function-name $(BDA_VE_INVOKE) --image-uri $(BDA_VE_IMAGE) --region $(AWS_REGION)
	@echo "Deploy complete: $(BDA_VE_IMAGE) -> $(BDA_VE_INVOKE)"

deploy-bda-video-engine-process: _bda-video-engine-push
	@aws lambda get-function --function-name $(BDA_VE_PROCESS) --region $(AWS_REGION) > /dev/null 2>&1 \
	  || { echo "ERROR: $(BDA_VE_PROCESS) does not exist"; exit 1; }
	aws lambda update-function-code \
	    --function-name $(BDA_VE_PROCESS) --image-uri $(BDA_VE_IMAGE) --region $(AWS_REGION)
	@echo "Deploy complete: $(BDA_VE_IMAGE) -> $(BDA_VE_PROCESS)"


# ── Content testing ────────────────────────────────────────────────────────────
# Per-type artifact config
ifeq ($(TYPE),VIDEO)
SOURCE_FILE := s3://$(BUCKET)/0ee0fe36-8a54-495f-a96a-9eac02da0f94/0ee0fe36-8a54-495f-a96a-9eac02da0f94.mp4
EXTENSION   := mp4
MIME_TYPE   := video/mp4
FILE_SIZE   := 10000000
endif

ifeq ($(TYPE),IMAGE)
SOURCE_FILE := s3://$(BUCKET)/1cc59676-cb04-47ca-baf2-d99303dfba18/1cc59676-cb04-47ca-baf2-d99303dfba18.jpg
EXTENSION   := jpg
MIME_TYPE   := image/jpeg
FILE_SIZE   := 1000000
endif

ifeq ($(TYPE),AUDIO)
SOURCE_FILE := s3://$(BUCKET)/audio/audio.mp3
EXTENSION   := mp3
MIME_TYPE   := audio/mpeg
FILE_SIZE   := 5000000
endif

ifeq ($(TYPE),TEXT)
SOURCE_FILE := s3://$(BUCKET)/007a2798-58a0-4486-b4a4-7b1b252ecf93/007a2798-58a0-4486-b4a4-7b1b252ecf93.txt
EXTENSION   := txt
MIME_TYPE   := text/plain
FILE_SIZE   := 1000
endif

content-create:
	@echo "Creating $(TYPE) content..."
	@CHECKSUM=$$(uuidgen); \
	METADATA_HASH=$$(uuidgen); \
	REQUEST_BODY=$$(jq -n \
	    --arg checksum "$$CHECKSUM" \
	    --arg metadata_hash "$$METADATA_HASH" \
	    --arg mime_type "$(MIME_TYPE)" \
	    --arg content_type "$(TYPE)" \
	    --arg filename "sample.$(EXTENSION)" \
	    --argjson file_size $(FILE_SIZE) \
	    '{ \
	        source_bucket: "$(BUCKET)", \
	        source_key: "uploaded/sample", \
	        original_filename: $$filename, \
	        file_size_bytes: $$file_size, \
	        mime_type: $$mime_type, \
	        content_type: $$content_type, \
	        checksum_sha256: $$checksum, \
	        metadata_hash: $$metadata_hash, \
	        media_metadata: {}, \
	        processing_config: {}, \
	        status: "PENDING", \
	        preprocessing_status: "PENDING", \
	        postprocessing_status: "PENDING" \
	    }'); \
	RESPONSE=$$(curl -s -X POST "$(API_URL)" \
	    -H "authorization: $(AUTH_TOKEN)" \
	    -H "content-type: application/json" \
	    -d "$$REQUEST_BODY"); \
	CONTENT_ID=$$(echo "$$RESPONSE" | jq -r '.content_id'); \
	if [ -z "$$CONTENT_ID" ] || [ "$$CONTENT_ID" = "null" ]; then \
	    echo "ERROR: Failed to create content"; \
	    echo "$$RESPONSE"; \
	    exit 1; \
	fi; \
	echo "Content ID: $$CONTENT_ID"; \
	echo "$(TYPE): $$CONTENT_ID" >> /tmp/content_ids.txt; \
	echo "Copying media file..."; \
	aws s3 cp "$(SOURCE_FILE)" "s3://$(BUCKET)/$$CONTENT_ID/$$CONTENT_ID.$(EXTENSION)" || exit 1; \
	echo "Created $(TYPE) content: $$CONTENT_ID"; \
	echo ""

content-create-all:
	@rm -f /tmp/content_ids.txt
	@$(MAKE) content-create TYPE=VIDEO
	@$(MAKE) content-create TYPE=IMAGE
	@$(MAKE) content-create TYPE=AUDIO
	@$(MAKE) content-create TYPE=TEXT
	@echo ""
	@echo "========================================="
	@echo "Created Content IDs"
	@echo "========================================="
	@cat /tmp/content_ids.txt

# make content-trigger CONTENT_ID=<id> CONTENT_TYPE=<VIDEO|IMAGE|AUDIO|TEXT>
content-trigger:
	@[ -n "$(CONTENT_ID)" ] || { \
	    echo "Usage: make content-trigger CONTENT_ID=<id> CONTENT_TYPE=<VIDEO|IMAGE|AUDIO|TEXT>"; \
	    exit 1; \
	}
	@INPUT=$$(jq -n \
	    --arg content_id "$(CONTENT_ID)" \
	    --arg content_type "$(CONTENT_TYPE)" \
	    --arg triggered_at "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	    '{ \
	        content_id: $$content_id, \
	        content_type: $$content_type, \
	        triggered_at: $$triggered_at, \
	        triggered_by: "content-inventory" \
	    }'); \
	echo "Starting workflow for $(CONTENT_ID)..."; \
	aws stepfunctions start-execution \
	    --state-machine-arn $(STATE_MACHINE_ARN) \
	    --input "$$INPUT" \
	    --region $(AWS_REGION)

content-create-and-trigger:
	@$(MAKE) content-create TYPE=$(TYPE)
	@CONTENT_ID=$$(tail -n 1 /tmp/content_ids.txt | awk '{print $$2}'); \
	echo ""; \
	echo "========================================="; \
	echo "Triggering workflow for $$CONTENT_ID"; \
	echo "========================================="; \
	INPUT=$$(jq -n \
	    --arg content_id "$$CONTENT_ID" \
	    --arg content_type "$(TYPE)" \
	    --arg triggered_at "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	    '{ \
	        content_id: $$content_id, \
	        content_type: $$content_type, \
	        triggered_at: $$triggered_at, \
	        triggered_by: "content-inventory" \
	    }'); \
	aws stepfunctions start-execution \
	    --state-machine-arn $(STATE_MACHINE_ARN) \
	    --input "$$INPUT" \
	    --region $(AWS_REGION)

content-trigger-all:
	@$(MAKE) content-create-and-trigger TYPE=VIDEO
	@$(MAKE) content-create-and-trigger TYPE=IMAGE
	@$(MAKE) content-create-and-trigger TYPE=AUDIO
	@$(MAKE) content-create-and-trigger TYPE=TEXT
