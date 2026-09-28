// Host-test loader for the same production scorer used by the static iOS bridge.
// SPDX-License-Identifier: AGPL-3.0-or-later
#include "TemplateScorer.hpp"

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void*) {
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_8) != JNI_OK
        || !OMRRegisterTemplateScorer(env)) return JNI_ERR;
    return JNI_VERSION_1_8;
}
