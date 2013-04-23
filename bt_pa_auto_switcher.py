#!/usr/bin/perl

# Script to automatically switch a Bluetooth headset between A2DP
# (High Fidelity Playback) and Telephony Duplex (HSP/HFP) when
# something tries to use the headset microphone.
#
# It also automatically mutes other audio / video sound sources during
# the call, so you should disable the "module-role-cork" plugin in
# /etc/pulse/default.pa. That plugin doesn't work well when this
# script is in use, so even if you decide to disable the auto-muting
# functionality by commenting it out below, you still need to disable
# the plugin to use this script.
#
# It also tries to remember the volume that was set on the headset for
# A2DP and HSP/HFP, and restore it when switching between them,
# because Pulseaudio doesn't seem to do this automatically and it's
# really annoying when it switches to full volume HSP/HFP and your
# ears get blasted.
#
# This should really be a Pulseaudio plugin, but it was faster for me
# to write a script than learn Pulseaudio development. :-)
#
# Configure the script to run when you log in, e.g., by adding it as a
# startup program in gnome-session-properties. It will wait for up to
# 30 seconds for Pulseaudio to start up before giving up, in case it's
# started before Pulseaudio is up. Note that if Pulseaudio restarts
# while you're logged in, you'll need to restart the script.

use Expect;

my $valid_clients = qr/(?:Skype|WEBRTC VoiceEngine)/;

my(%connections, %muted);

$start_time = time();
while (($exp && ($patidx = $exp->expect(undef, '-re', '.*\n'))) ||
       $start_time) {
    if (! $patidx) {
	# No successful output yet... first time through the loop, so
	# we need to initialize, or Pulseaudio hasn't started yet.
	if (time() - $start_time < 30) {
	    $exp = Expect->spawn('pactl', 'subscribe') or die;
	    $exp->log_user(0);
	    $exp->log_stdout(0);
	    sleep(1);
	    next;
	}
	last;
    }
    # We've successfully read at least one event, so we're done
    # waiting for Pulseaudio to start up.
    $start_time = undef;

    $_ = $exp->match();
    next if (/on client |'change'/);
    if (/^Event 'new' on (sink-input|source-output) \#(\d+)/) {
	my($type) = $1;
	my($num) = $2;
	next if (! &new($type, $num));
	if (&both && ! &hsp) {
	    &switch;
	}
    }
    elsif (/^Event 'remove' on (sink-input|source-output) \#(\d+)/) {
	my($type) = $1;
	my($num) = $2;
	next if (! &remove($type, $num));
	if (&neither && &hsp) {
	    &switch_back;
	}
    }
}

sub new {
    my($type, $num) = @_;
    my $client = &get_client($type, $num);
    return undef if (! $client);
    print "NEW: $type / $num / $client\n";
    $connections{$type}->{$num} = 1;
}

sub remove {
    my($type, $num) = @_;
    return undef if (! delete($connections{$type}->{$num}));
    print "REMOVE: $type / $num\n";
    return 1;
}

sub both {
    return undef if (scalar keys %connections != 2);

    map {
	return undef if (! %{$connections{$_}});
    } keys %connections;

    return 1;
}

sub neither {
    map {
	return undef if (%{$connections{$_}});
    } keys %connections;

    return 1;
}

sub get_client {
    local($_);
    my($type, $num) = @_;
    open(PACMD, "-|", "pacmd list-${type}s") or die;
    my($in) = 0;
    while (<PACMD>) {
	if (/^\s*index:\s+$num\b/) {
	    $in = 1;
	    next;
	}
	elsif ($in && /^\s*index:\s+\d+\b/) {
	    return undef;
	}
	elsif ($in && /^\s+application\.name = "($valid_clients)"/o) {
	    print "good client ($type, $num): $1\n";
	    return $1;
	}
	elsif ($in && /^\s+application\.name = "(.*)"/) {
	    print "bad client ($type, $num): $1\n";
	    return undef;
	}
    }
    return undef;
}

sub switch {
    ($sink_name, $card_name) = &get_running_bluez_sink();
    return if (! $sink_name);
    my $new_volume = &get_sink_volume($sink_name);
    ($source_name = $sink_name) =~ s/sink/source/;
    &mute_corked();
    print "Switching\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    print(PACMD "set-card-profile $card_name hsp\n");
    print(PACMD "set-default-source $source_name\n");
    print(PACMD "set-default-sink $sink_name\n");
    foreach my $sink (keys %{$connections{'sink-input'}}) {
	print(PACMD "move-sink-input $sink $sink_name\n");
    }
    foreach my $source (keys %{$connections{'source-output'}}) {
	print(PACMD "move-source-output $source $source_name\n");
    }
    if (defined($save_volume)) {
	print "Resetting volume to $save_volume\n";
	print(PACMD "set-sink-volume $sink_name $save_volume\n");
    }
    close(PACMD) || warn "pacmd failed\n";
    $save_volume = $new_volume;
}

sub switch_back {
    my($sink_name, $card_name) = &get_running_bluez_sink();
    if (! $sink_name) {
	return;
    }
    my $new_volume = &get_sink_volume($sink_name);
    print "Switching back\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    print(PACMD "set-card-profile $card_name a2dp\n");
    print(PACMD "set-default-sink $sink_name\n");
    if (defined($save_volume)) {
	print "Resetting volume to $save_volume\n";
	print(PACMD "set-sink-volume $sink_name $save_volume");
    }
    close(PACMD) || warn "pacmd failed\n";
    $save_volume = $new_volume;
    &unmute_corked();
}

sub get_running_bluez_sink {
    local($_);
    my($sink);
    open(STAT, "-|", "pactl stat");
    while (<STAT>) {
	if (/^Default Sink/) {
	    if (/(bluez_sink.*)/) {
		$sink = $1;
		last;
	    }
	    return undef;
	}
    }
    if ($sink) {
	my($card) = $sink;
	$card =~ s/sink/card/;
	return($sink, $card);
    }
    return ();
}

sub get_sink_volume {
    local($_);
    my($sink) = @_;
    my($sink_re) = $sink;
    $sink_re =~ s/(\W)/\\$1/g;
    my($pct, $steps);
    my $in = 0;
    open(PACMD, "-|", "pacmd list-sinks");
    while (<PACMD>) {
	if (/^\s*name: <$sink_re>/) {
	    $in = 1;
	    next;
	}
	elsif ($in && m/^\s*name:/) {
	    return undef;
	}
	elsif ($in && /^\s*volume:.*?\b(\d+)%/) {
	    $pct = $1;
	    next;
	}
	elsif ($in && /^\s*volume steps:\s+(\d+)/) {
	    my $steps = $1;
	    my $volume = int($pct / 100 * $steps);
	    print "$sink volume: $volume / $steps\n";
	    return $volume;
	}
    }
    return undef;
}

sub get_current_profile {
    local($_);
    my($card) = @_;
    my($card_re) = $card;
    my $in = 0;
    $card_re =~ s/(\W)/\\$1/g;
    open(PACMD, "-|", "pacmd list-cards") or die;
    while (<PACMD>) {
	if (/^\s*name: <$card_re>/) {
	    $in = 1;
	    next;
	}
	elsif ($in && m/^\s*name:/) {
	    return undef;
	}
	elsif ($in && /^\s*active profile: <(.*)>/) {
	    return $1;
	}
    }
    return undef;
}

sub hsp {
    ($sink, $card) = &get_running_bluez_sink();
    $profile = &get_current_profile($card);
    $profile eq 'hsp';
}

sub mute_corked {
    local($_);
    local($/) = "index:";
    open(PACMD, "-|", "pacmd list-sink-inputs");
    while (<PACMD>) {
	my($app, $num);
	if (/START_CORKED/ && /muted: no/ &&
	    (($app) = /application\.name = "(.*)"/) &&
	    (($num) = /^\s*(\d+)/) && ! $connections{'sink-input'}->{$num}) {
	    $muted{$num} = $app;
	}
    }
    close(PACMD);
    return if (! %muted);
    my(%apps) = reverse %muted;
    print "Muting ", join(" ", sort keys %apps), "\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    foreach my $input (keys %muted) {
	print(PACMD "set-sink-input-mute $input 1\n");
	print("set-sink-input-mute $input 1\n");
    }
    close(PACMD) || warn "pacmd failed\n";
}

sub unmute_corked {
    return if (! %muted);
    print "Unmuting\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    foreach my $input (keys %muted) {
	print(PACMD "set-sink-input-mute $input 0\n");
    }
    close(PACMD) || warn "pacmd failed\n";
    %muted = ()
}
