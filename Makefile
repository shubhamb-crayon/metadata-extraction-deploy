# ── Config ────────────────────────────────────────────────────────────────────
-include config.mk
APP_DIR        ?= $(error APP_DIR not set — copy config.mk.example to config.mk)
AWS_ACCOUNT_ID ?= $(error AWS_ACCOUNT_ID not set — copy config.mk.example to config.mk)

AWS_REGION   := ap-southeast-1
ECR_REGISTRY := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
env          ?= dev

ecr_uri   = $(ECR_REGISTRY)/metadata-extraction/$(1):latest
lambda_fn = function-metadata-extraction-$(1)-$(env)

.PHONY: \
    ecr-login \
    deploy-lambda \
    deploy-asr deploy-intelligent-frame-sampling \
    _bda-image-engine-push deploy-bda-image-engine-invoke deploy-bda-image-engine-process \
    _bda-video-engine-push deploy-bda-video-engine-invoke deploy-bda-video-engine-process


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


# ── Lambda ────────────────────────────────────────────────────────────────────
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


# ── ECS: automated-speech-recognition (arm64) ────────────────────────────────
deploy-asr:
	$(call ensure-ecr-repo,automated-speech-recognition)
	docker buildx build \
	    -f $(APP_DIR)/services/automated-speech-recognition/Dockerfile \
	    --platform linux/arm64 --provenance=false --load \
	    -t $(call ecr_uri,automated-speech-recognition) $(APP_DIR)
	docker push $(call ecr_uri,automated-speech-recognition)
	@echo "Deploy complete: $(call ecr_uri,automated-speech-recognition)"


# ── ECS: mdm-intelligent-frame-sampling (amd64) ──────────────────────────────
deploy-intelligent-frame-sampling:
	$(call ensure-ecr-repo,mdm-intelligent-frame-sampling)
	docker buildx build \
	    -f $(APP_DIR)/services/mdm-intelligent-frame-sampling/Dockerfile \
	    --platform linux/amd64 --provenance=false --load \
	    -t $(call ecr_uri,mdm-intelligent-frame-sampling) $(APP_DIR)
	docker push $(call ecr_uri,mdm-intelligent-frame-sampling)
	@echo "Deploy complete: $(call ecr_uri,mdm-intelligent-frame-sampling)"


# ── BDA Image Engine (two Lambdas, one shared image) ─────────────────────────
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


# ── BDA Video Engine (two Lambdas, one shared image) ─────────────────────────
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
